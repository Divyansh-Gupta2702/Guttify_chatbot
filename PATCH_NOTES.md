# GutGPT v18.3 — assessment status preservation fix

## Change

In `_write_customer_records()`, the legacy customer-history upsert no longer overwrites an existing `customer_assessments.status` with `completed`, and no longer overwrites its `completed_at` timestamp. It still updates the assessment description/customer association. The normalized checkpoint writer `_persist_assessment_checkpoint()` remains the owner of assessment lifecycle status.

## Why

The observed database row had `customer_assessments.status = 'completed'` while `assessment_state.checkpoint.active = true`, `diagnosis_complete = false`, and `ended = false`. The old history upsert could force the existing row to `completed`, creating exactly this mismatch.

## Verification

- `python -m py_compile app.py` passed.
- Regression tests assert the legacy upsert cannot force existing rows to completed and that checkpoint persistence still determines status.
- These are source-level tests only. A live PostgreSQL/widget refresh-resume test is still required.

## Safety

This patch does not change database schema, delete records, or modify diagnosis, NLU, safety, question-flow, or recommendation rules. It does not retroactively repair rows already marked completed; test first, then inspect/recover affected rows separately with a reviewed migration if needed.
