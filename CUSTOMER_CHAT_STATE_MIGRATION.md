# Customer and per-assessment storage

The application uses PostgreSQL only. On startup, `_init_postgres()` creates or upgrades the tables.

## Tables

- `customers`: `customer_id`, `name`, `age`, `contact`, `location`, `created_at`, `updated_at`, `likely_assessment`.
- `customer_chat_state`: customer/session bindings, consent, guest-token hash/expiry, and other authentication/session metadata. Legacy `active_checkpoint` and `chat_history` columns remain for upgrade compatibility but are cleared after a normalized checkpoint is written.
- `assessment_messages`: one row per user or assistant message, ordered by `sequence_no`, with a `turn_id` to avoid duplicate writes of the same turn.
- `assessment_state`: latest resumable `SessionState` checkpoint per assessment.
- `customer_assessments`: compatibility summary of completed assessment outcomes.
- `api_rate_limits`: shared API rate-limit state.

Chat messages are no longer written to a single per-customer JSON history field. The normalized message log is the source for restored transcript messages; `assessment_state` is the source for the rule-engine checkpoint. The diagnosis, NLU, question flow, safety checks, and recommendation rules are not changed by this storage layer.

## Existing database

Back up PostgreSQL before deploying schema changes. Startup migrates legacy `record_json` fields and embedded completed-assessment summaries before removing legacy columns from `customers`. The normalized tables are created idempotently. After deployment, verify new registration, a few chat turns, refresh/resume, completion, and a second assessment before considering the rollout complete. Do not delete the PostgreSQL Docker volume during an application rebuild.


Assessment lifecycle and ownership are stored in `customer_assessments`. Chat messages and resumable state reference that table directly; the redundant `assessment_sessions` and `assessment_session_bindings` tables are no longer created and are removed during schema initialization after any lifecycle rows are copied.
