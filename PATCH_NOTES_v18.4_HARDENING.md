# GutGPT v18.4 – Production hardening patch

This patch is deliberately limited to conversation reliability and assessment persistence. It does not change the clinical rule engine, NLU extraction schema, diagnosis rules, safety checks, product eligibility, or recommendation logic.

## Changes

### 1. Intent classification output budget
- Increased the conversation-intent classifier output allowance from 140 to 260 tokens.
- Kept the existing strict JSON parsing, intent allowlist, confidence validation, and fail-closed behaviour.
- This reduces avoidable truncation risk; malformed or truncated responses still fall back safely.

### 2. Bounded context for general answers
- General educational answers now receive at most the latest four user/assistant turns.
- Each turn is normalized and capped at 300 characters (with the helper's hard cap retained).
- The prompt explicitly treats history as untrusted context, not instructions or clinical evidence.
- No customer profile, database record, or additional personal data is added to the prompt.

### 3. Atomic initial assessment checkpoint
- Explicitly creating a new assessment now inserts its initial `assessment_state` checkpoint in the same PostgreSQL transaction as the `customer_assessments` row and active-assessment pointer.
- The checkpoint stores the initial serialized rule-engine session state, is marked active, and carries the new assessment ID.
- The existing restore guard for genuinely missing or invalid checkpoints remains intact.
- No schema migration is required; `assessment_state` is already created by the existing schema initializer.

### 4. Regression tests
- Added tests for the classifier output budget and bounded contextual history.
- Added a static transaction-contract test verifying that the initial checkpoint insert is inside the assessment-creation transaction.

## Validation performed in this environment
- `python -m py_compile conversation_intelligence.py app.py` – passed.
- Targeted tests: 43 passed, 1 deselected.
- A broader targeted run produced 3 environment/baseline failures: this runtime does not have `langchain_core` installed for app-import tests, and an existing provider-default test expects Groq while the checked-in provider code defaults to Gemini. These are not caused by this patch.
- PostgreSQL integration tests and live Groq/Gemini calls were not run here. Run them on the deployment/test environment before production rollout.

## Deployment
1. Back up the current project and PostgreSQL database.
2. Upload and extract this project copy, or apply the changed files to the existing checkout.
3. Install dependencies from the project's pinned requirements in the server virtual environment.
4. Run the targeted tests and the complete existing regression suite on the server/test environment.
5. Restart `gutgpt.service` only after tests pass.
6. Verify that a newly created assessment has a matching row in `assessment_state` immediately, before sending the first chat message.

Suggested PostgreSQL verification (replace the customer ID with a test customer):

```sql
SELECT a.assessment_id, a.status,
       (s.assessment_id IS NOT NULL) AS has_checkpoint,
       s.checkpoint->>'active' AS checkpoint_active
FROM customer_assessments AS a
LEFT JOIN assessment_state AS s USING (assessment_id)
WHERE a.customer_id = '<test-customer-id>'
ORDER BY a.started_at DESC
LIMIT 5;
```
