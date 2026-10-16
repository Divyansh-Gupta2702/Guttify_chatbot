# GutGPT PostgreSQL persistence setup (v18.3)

GutGPT now uses PostgreSQL for customer profiles and completed assessment records whenever `DATABASE_URL` is configured. When `DATABASE_URL` is absent, local development retains the existing JSON customer store and SQLite assessment store so the existing local tests and workflow remain compatible.

## Render setup

1. Create a PostgreSQL database in the Render dashboard.
2. In the GutGPT web service, open **Environment** and add `DATABASE_URL` with the database's **Internal Database URL** (when the database and web service are in the same Render region/account).
3. Deploy the code with the updated `requirements.txt`; it installs `psycopg[binary]`.
4. Restart/redeploy the web service. On the first customer read/write or assessment save, GutGPT creates the `gutgpt_customers` and `customer_assessments` tables and indexes.
5. Test a new registration and completed assessment. Check `/api/admin/customers` and `/api/admin/assessments` using the configured `GUTGPT_ADMIN_TOKEN`.

Keep `DATABASE_URL`, `JWT_SECRET_KEY`, `GUTGPT_ADMIN_TOKEN`, and API keys in Render environment variables only. Never commit real secrets. Keep JWT signing configured with a random secret of at least 32 bytes.

## Tables

- `gutgpt_customers`: one row per session/profile; the JSONB `data` field preserves the existing customer record fields including customer ID and guest-token metadata.
- `customer_assessments`: completed assessment summary, diagnosis, symptom state, screening data, recommendations, customer ID, and session ID.

Customer JSON records are imported into PostgreSQL on first use only when the PostgreSQL customer table is empty and `customer_data.json` exists. The migration is deliberately not repeated once PostgreSQL contains records, to avoid overwriting newer database data.

The existing local SQLite assessment history is not automatically copied to PostgreSQL. If historical assessments must be retained, perform a separately verified migration before switching production traffic.

## Verification / limitations

- `DATABASE_URL` selects PostgreSQL; unset it to use local JSON/SQLite development storage.
- The diagnosis engine, NLU resolution, question flow, safety checks, and recommendation rules are unchanged.
- Run the existing test suite in an environment with all project requirements installed.
- The current environment used to prepare this patch did not have `langchain_core`, so pytest collection could not run here; Python syntax compilation succeeded. Test PostgreSQL connectivity and all regression tests before production rollout.
- Free database plans have limits and may expire. Keep a secure backup/retention plan before storing real customer or health data.
