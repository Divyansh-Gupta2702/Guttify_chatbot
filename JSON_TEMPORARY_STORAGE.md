# Temporary JSON storage

This build stores customer registration details and the final assessment fields together in `customer_data.json`. Each customer row includes `likely_assessment` (the likely assessment value from the completed screening), `final_symptom_summary` (the final summary of symptoms). It does not create a separate assessment table or `assessment_data.json` file. It does not use PostgreSQL or SQLite for these records, even if an old `DATABASE_URL` environment variable remains configured.

## Admin panel

1. Set a strong `GUTGPT_ADMIN_TOKEN` in the Render service environment.
2. Deploy the application and open `/admin`.
3. Sign in using the admin token. The single customer table displays registration details plus the two assessment columns.
4. Use **Download customer JSON** to export all customer records and assessment summary fields.

Only completed assessment results update the two assessment fields. Intermediate questions do not overwrite the stored assessment summary. The assessment fields are updated on the matching customer record by session ID. Existing customer JSON records remain readable; older records simply display blank values for the new fields until an assessment completes.

## Temporary storage warning

On Render's free service filesystem, JSON files can be lost when the instance restarts, redeploys, or is replaced. This is suitable for temporary testing only, not durable storage for real customer data. Keep the admin token secret and use dummy data while testing.
