# GutGPT patch verification — 2026-10-26

## Changes
- Changed the active-assessment lookup to `LEFT JOIN assessment_state`, so an active assessment missing a checkpoint is not mistaken for no active assessment.
- Resume now returns explicit `ASSESSMENT_CHECKPOINT_UNAVAILABLE` or `ASSESSMENT_CHECKPOINT_INVALID` statuses for active assessments whose checkpoint cannot be restored.
- The widget only allows `RESUMED` and `NO_ACTIVE_ASSESSMENT` as recognized resume statuses; any other status pauses chat and tells the customer their assessment was not restarted.
- Empty message arrays remain valid for a resumed assessment when the backend provides a valid `assessment_id`.
- Updated security tests to align with PostgreSQL-only rate limiting: no in-memory limiter fallback is introduced. Unit tests isolate token/export behavior from the database-backed rate limiter.

## Verification performed
- `python -m py_compile app.py tests/test_assessment_resume_contract.py tests/test_phase2b_security_basics.py tests/test_security_hardening_followup.py` — passed.
- `python -m pytest -q tests/test_assessment_resume_contract.py` — 3 passed.
- Attempted `python -m pytest -q tests/test_assessment_resume_contract.py tests/test_postgres_only_storage.py` — blocked during collection because `langchain_core` is not installed in this environment.
- Attempted dependency installation from `requirements.txt` — blocked because this environment has no DNS/network access.

## Not claimed
The full suite and PostgreSQL integration behavior have not been verified here. Run the full suite in the project's configured virtual environment against the intended test database before deployment.


## Exact follow-up fix: incompatible active checkpoint
- Fixed `_restore_assessment_checkpoint()`: when a database-confirmed active assessment's checkpoint cannot be reconstructed (`TypeError`/`ValueError`), it now returns `ASSESSMENT_CHECKPOINT_INVALID` with the assessment ID instead of `None`.
- `None` remains possible only when there is no known active normalized assessment and the legacy fallback does not yield a resumable checkpoint.
- Added a static regression guard for this exact exception path.
- This is a source-level fix; PostgreSQL integration and live widget behavior still need to be tested against the configured test database.
