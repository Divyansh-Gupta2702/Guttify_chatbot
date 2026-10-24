# GutGPT v18.3 — in-progress assessment recovery update

## What changed

- The backend now saves an unfinished registered customer's conversation state and transcript to the configured customer store after each completed chat turn.
- The new `POST /api/customer/resume` endpoint restores only the checkpoint belonging to the authenticated customer already bound to the newly created session by `/api/customer/restore`.
- The Shopify widget attempts to resume the unfinished assessment after restoring the customer profile and renders the saved transcript. If no active checkpoint exists, it offers a fresh assessment.
- Completed/urgent assessments are not retained as active checkpoints. Existing completed assessment history and the deterministic diagnostic/recommendation pipeline are not intentionally changed.
- Checkpoint data uses the existing storage configuration: PostgreSQL when `DATABASE_URL` is set; otherwise the configured JSON customer-data file. In JSON mode, the file must be on a persistent mounted volume in deployments, or data can be lost when the container is replaced.

## Important behavior and limits

- A checkpoint is written after a chat response has been processed and added to history. A network interruption before the server finishes processing that turn may mean that last answer has not yet been checkpointed.
- The resume endpoint relies on the existing guest-token/profile restore flow and server-side customer/session binding; it does not accept a customer ID from the browser as proof of identity.
- Do not deploy this update until regression tests pass in the project's configured environment and a real refresh/restart test has been performed against a backup or staging copy of the data.

## Validation performed in this environment

- Python syntax compilation passed for `app.py`, `guttify_agent.py`, and `intent_parser.py`.
- `node --check gutgpt-widget.js` passed.
- Full pytest collection could not be completed in this environment because the runtime lacks the project dependency `langchain_core`. Install the project's declared dependencies and rerun the full test suite before production deployment.
