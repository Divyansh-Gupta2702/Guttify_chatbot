# GutGPT PostgreSQL persistence (Phase 2A)

This build uses PostgreSQL whenever `DATABASE_URL` is set. If it is unset, the app keeps the existing local JSON storage behavior for backward-compatible tests/development. Production deployments should set `DATABASE_URL` and should not rely on a local JSON file for persistent storage.

## 1. Install the Python driver

```powershell
python -m pip install "psycopg[binary]>=3.2,<4.0"
```

The dependency is also included in `requirements.txt`.

## 2. Set local connection configuration (PowerShell)

```powershell
$env:DATABASE_URL = "postgresql://postgres:YOUR_PASSWORD@localhost:5432/gutgpt"
$env:JWT_SECRET_KEY = "replace-with-a-random-secret-at-least-32-bytes-long"
$env:GROQ_API_KEY = "your-groq-api-key"
$env:ALLOWED_ORIGINS = "http://localhost:3000,http://localhost:5173,http://localhost:8000"
$env:GUTGPT_ADMIN_TOKEN = "replace-with-a-long-random-admin-token"
```

Use your actual PostgreSQL password locally. Do not commit `.env` files, passwords, JWT secrets, or API keys to GitHub. For production, set these in the hosting provider's environment-variable settings.

## 3. Schema creation and upgrade

At application startup, when `DATABASE_URL` is configured, GutGPT creates or upgrades the `customers` and `customer_assessments` tables. This supports the simple tables created by the initial manual setup. Customer IDs are UUID strings because they are also the signed guest-token subject. Assessment rows reference the customer and have a unique session ID so retries do not create duplicate assessment rows.

Timestamps are stored as timezone-aware PostgreSQL timestamps. Displayed registration/assessment timestamps use `Asia/Kolkata` (IST); timestamps should not be stored as naive local time.

## 4. Start the backend

From the folder containing `app.py`:

```powershell
python -m pip install -r requirements.txt
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

The database schema is initialized by the FastAPI lifespan. A database connection or schema error is logged and startup fails rather than silently using JSON when `DATABASE_URL` is set.

## 5. Check tables in psql

```sql
\c gutgpt
\dt
SELECT customer_id, name, contact, location, created_at FROM customers;
SELECT customer_id, session_id, assessment, completed_at FROM customer_assessments ORDER BY completed_at DESC;
```

The customer table stores one profile per guest-token identity; multiple completed diagnostic sessions are stored in `customer_assessments`. A returning profile is restored only with a valid guest token whose JTI hash matches the stored profile. Contact number is not used as an identity key.

## Notes

- The diagnosis/rule engine, NLU resolution, safety checks, question flow, and product recommendation logic are unchanged.
- Session conversation state remains in memory as before; PostgreSQL persists customer profiles and completed assessment history, not active chat transcripts.
- The JSON admin download endpoint remains for compatibility, but reads from the configured storage backend.
- If existing JSON customer records must be migrated, back up the JSON file first and perform a deliberate one-time migration; this build does not automatically import JSON data into PostgreSQL.
