# GutGPT temporary JSON storage (v18.3)

This build stores registered customer profiles in `customer_data.json` and completed assessments in `assessment_data.json`. It does not use PostgreSQL or SQLite for these records, even if an old `DATABASE_URL` environment variable remains configured.

## Admin panel

1. Set `GUTGPT_ADMIN_TOKEN` in the Render service environment to a long, unique secret.
2. Keep `JWT_SECRET_KEY` configured to a random secret of at least 32 bytes.
3. Deploy the application and open `/admin` on the same service domain.
4. Enter the admin token. The panel displays customer records and completed assessments. Use the separate buttons to download `customer_data.json` and `assessment_data.json`.

## JSON file locations

By default, both files are created beside `app.py`. You can override their locations with `CUSTOMER_DATA_FILE` and `ASSESSMENT_DATA_FILE`. The files are created automatically when the first relevant record is saved. Writes use a temporary file and atomic replacement to reduce the risk of a partially written JSON file.

## Important Render limitation

This is temporary storage for testing. On Render's free web-service filesystem, local files are not guaranteed to survive restarts, redeploys, or instance replacement, and separate instances do not share local files. Do not use this as reliable production storage for real customer or health data. Use a persistent disk or managed database before production. Restrict the admin token and protect downloaded JSON files because they contain personal and health-related information.

The assessment file stores the latest completed assessment per session, including diagnosis/pattern, symptom summary/state, screening details, recommendations, timestamps, and customer/session identifiers. The existing NLU, question flow, safety logic, diagnosis rules, and recommendation rules are unchanged.
