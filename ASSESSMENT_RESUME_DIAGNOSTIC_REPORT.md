# GutGPT v18.3 Assessment Resume — Diagnostic and Patch Report

## Scope and evidence

Inspected the uploaded `BOT.zip` source archive, including `app.py`, `gutgpt-widget.js`, PostgreSQL startup schema, and existing tests. The archive identifies itself as `18.3-cookie-guest-30d` in `VERSION.txt`. No live PostgreSQL connection or Shopify browser session was available, so the production database contents and real storefront behavior were not verified. The database backup dump was not opened or modified.

## Findings

### Confirmed code defects

1. **Widget conflated resume failure with no active assessment.** In `gutgpt-widget.js` (`initSession`, originally around lines 550–570), a failed `/api/customer/resume` request set `resumeFailed`, but the code still rendered the normal “You can start a new assessment” message. The warning appeared in the status area, but the input form remained available. This could make a real restoration failure look like a clean slate and permit the user to send answers into a fresh in-memory session.
2. **Backend query masked inconsistent active assessments.** In `app.py` (`_restore_assessment_checkpoint`, originally around lines 884–892), an inner join plus a JSON checkpoint-active filter excluded an `active` `customer_assessments` row if its `assessment_state` row was missing, malformed, or marked inactive. The endpoint then returned `NO_ACTIVE_ASSESSMENT`, which incorrectly treated inconsistent persisted data as a genuine absence of an active assessment.
3. **Malformed checkpoint was silently treated as no active assessment.** The restore helper returned `None` when the checkpoint state was missing required structure or could not be deserialized. The API therefore could tell the widget to offer a new assessment instead of returning a recoverable error.

These are confirmed defects in the uploaded code. **They are not proof that any one of them is the exact state of the production customer's database.** To establish that, inspect sanitized live rows for the affected customer: active assessment ID/status, whether `assessment_state` exists and has `active=true`, and message count by that assessment ID. Do not export or log health-message contents or authentication tokens.

### Request flow verified from source

1. Widget creates a fresh transient `/api/session`.
2. Widget calls `/api/customer/restore`; backend validates the guest credential and binds the new session to the authenticated customer.
3. Widget calls `/api/customer/resume`.
4. Backend finds an active `customer_assessments` row, restores its `assessment_state` checkpoint into `conversation_manager.sessions[new_session_id]`, restores ordered `assessment_messages` into `HISTORY[new_session_id]`, and binds the new session to the customer and canonical assessment ID.
5. Subsequent `/api/chat` calls run through the existing `ConversationManager` and deterministic question/rule flow.

The code's normal persistence path writes the latest state and the newly appended user/assistant pair into `assessment_state` and `assessment_messages` in one PostgreSQL transaction. Live commit success, actual row consistency, and cross-process behavior were not testable here.

## Changes made

- `app.py`
  - Changed active-assessment lookup to a `LEFT JOIN`, so an active lifecycle row with a missing checkpoint is detected instead of hidden.
  - Returns HTTP 503 with a recoverable error when an active assessment has a missing/inactive checkpoint or a checkpoint cannot be deserialized.
  - Keeps `NO_ACTIVE_ASSESSMENT` for the case where no active lifecycle row is found and no valid legacy checkpoint exists.
  - No schema changes, migrations, new tables, or storage fallbacks were added.
- `gutgpt-widget.js`
  - A resume network/API failure or unexpected response no longer renders the “start a new assessment” state.
  - Hides the answer form while restoration is unresolved and tells the customer to reload/retry; it does not silently start over.
  - Accepts a valid `RESUMED` response even if the transcript array is empty, rather than misclassifying it as no active assessment.
- `tests/test_assessment_resume_contract.py`
  - Adds source-level regression guards for the failure-vs-no-active distinction and widget behavior. These are not substitutes for PostgreSQL/browser integration tests.

## Checks run

- `python -m py_compile app.py tests/test_assessment_resume_contract.py` — passed.
- `node --check gutgpt-widget.js` — passed.
- `python -m pytest -q tests/test_assessment_resume_contract.py` — **3 passed**.
- Focused existing tests (`tests/test_postgres_only_storage.py`, `tests/test_assessment_persistence.py`, `tests/test_v18_3_production_log_regressions.py`) — **blocked during collection** because `langchain_core` is not installed (`ModuleNotFoundError`). No test results are claimed for those suites.
- No PostgreSQL schema check, database-backed resume test, full test suite, or real Shopify browser flow was run.

## Database changes

None. The patch does not alter tables, columns, constraints, indexes, or migrations. No customer data or Docker volumes were changed.

## Manual verification checklist

1. Back up the production PostgreSQL database using the normal operational backup procedure before deployment; test first against staging or a restored disposable copy.
2. Register a test customer, start an assessment, and answer at least three questions.
3. Verify one active `customer_assessments` row, one active `assessment_state` checkpoint, and ordered `assessment_messages` for the same `assessment_id`. Query only IDs, status, timestamps, and counts; avoid selecting message content.
4. Refresh the Shopify page. Confirm the customer remains recognized, prior messages render in order, and the next question continues from the saved state.
5. Simulate resume API failure in browser devtools. Confirm the answer form stays hidden and no new assessment is started.
6. Test a customer with no active assessment; only then should the widget offer a new assessment.
7. Test missing checkpoint on staging. The API should return a recoverable 503, not `NO_ACTIVE_ASSESSMENT`.
8. Run the full suite with the project's declared dependencies and execute the browser flow in each supported storefront browser.

## Rollback

Revert `app.py` and `gutgpt-widget.js` to the versions from the pre-deployment archive and redeploy the prior application image. There are no schema changes to roll back. Do not drop tables, delete assessment history, or remove the PostgreSQL Docker volume.
