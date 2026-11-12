# PostgreSQL schema and startup migration guide

This guide documents the schema created and upgraded by `app._init_postgres()`.
The migration runs automatically during application startup. It does not
replace the database, but it does alter tables and drop legacy columns/tables.
Back up production before deploying a version that runs this migration.

## Current tables

- `customers` stores the profile: customer ID, name, age, contact, location,
  creation/update timestamps, and latest assessment summary.
- `customer_chat_state` stores registration/session bindings, consent, guest
  token JTI hash and expiry, active assessment ID, checkpoint, chat state,
  history, and update timestamp.
- `customer_assessments` stores one assessment lifecycle row per assessment.
- `assessment_messages` stores ordered user/assistant messages for an
  assessment.
- `assessment_state` stores the latest JSONB checkpoint for an assessment.
- `api_rate_limits`, `chat_idempotency`, `groq_shared_usage_window`, and
  `groq_shared_leases` support shared request limiting and idempotent chat
  handling.

Assessment message and state rows reference `customer_assessments` with
`ON DELETE CASCADE`. Customer assessments and chat state reference `customers`
with `ON DELETE CASCADE`.

## Startup migration behavior

Within a PostgreSQL transaction, startup creates missing current tables and
indexes, adds supported columns, and upgrades the assessment foreign keys. If
the legacy `customers.record_json` column exists, the migration copies session,
consent, guest-token metadata, bound session IDs, checkpoint/chat state, and
embedded assessment summaries into the normalized tables before dropping that
column. It then removes legacy authentication/session columns from `customers`
and drops every other customer column outside the current profile allowlist.

If `assessment_sessions` exists, its assessment IDs, customer IDs, status, and
timestamps are copied into `customer_assessments`. The migration then drops
`assessment_sessions` and `assessment_session_bindings`. **The current migration
does not copy rows from `assessment_session_bindings`.** If your database has
rows in that legacy table, inspect and export them before startup; do not assume
those mappings will be retained. Confirm that each old assessment has the
required customer/session association before deploying.

The migration targets tables in PostgreSQL's `current_schema()`. Make sure the
application role connects with the intended schema as its search path. Existing
schemas with unexpected constraints, invalid profile values, or incompatible
legacy table shapes can cause startup to fail; the transaction should roll back
the incomplete migration, but the pre-deployment backup remains essential.

## Safe deployment procedure

1. Identify the database and schema used by the application from its protected
   server configuration. Do not print or share the connection URL.
2. Take and verify a PostgreSQL backup using the site's normal backup process.
3. On a restored staging copy, run the new application and inspect startup logs
   for migration errors.
4. Compare pre/post row counts for `customers`, assessment records, messages,
   checkpoints, and any legacy binding table. Confirm returning-customer restore
   and assessment history on staging.
5. Deploy to production only after these checks pass. Keep the backup until the
   application and customer restore flow have been verified.

Docker Compose persists PostgreSQL in the `gutgpt_postgres_data` named volume.
Rebuilding the backend does not require deleting or recreating that volume.
