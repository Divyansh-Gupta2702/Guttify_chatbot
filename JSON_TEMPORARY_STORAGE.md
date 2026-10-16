# GutGPT temporary JSON storage

Customer registration details remain in one customer profile in `customer_data.json`. Each completed diagnosis is appended to that profile's `assessments` array with an assessment ID, session ID, assessment value, and completion timestamp. The top-level `likely_assessment` field remains as a compatibility/latest-result field for the admin dashboard's **Assessment** column. Registration city is displayed as **Location**. Contact numbers accept digits only (7–15 digits).

A returning customer should restore their profile with their guest token; the active session is linked to the same customer ID so new diagnoses are appended to their history rather than replacing previous diagnoses or creating a second profile. Existing records without an `assessments` array are upgraded when a new assessment is saved.

The JSON file is temporary on Render's free filesystem and can be lost on restart or redeployment. Use dummy data for testing and protect the admin token.

All customer-facing stored timestamps (including diagnosis `completed_at`, profile `created_at`, and `updated_at`) use India Standard Time (`Asia/Kolkata`, UTC+05:30) and include the timezone offset. JWT expiry calculations remain UTC-based internally.
