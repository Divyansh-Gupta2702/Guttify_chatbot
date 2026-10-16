# GutGPT v18.3 — Phase 1 Symptom Summary and Bristol Chart Selection

## What changed

- Added a deterministic, read-only symptom summary using the structured `SymptomState` values.
- Non-urgent assessments pause at `SUMMARY_REVIEW` before final assessment and product recommendation.
- Customers can confirm the summary or correct recognized details. Bristol type, duration, age, severity, and explicit symptom corrections are handled through deterministic parsing; unrecognized corrections do not mutate state.
- Summary confirmation is not passed to the generic NLU as a bare `yes`, preventing a confirmation from being misread as a positive answer to unrelated clinical fields.
- Added clickable Bristol Stool Chart Type 1–7 options to the standalone frontend and Shopify widget. Selection is submitted through the existing chat API as `Bristol type N`.
- The selected Bristol type remains a supporting feature in the existing clinical rule engine. It can change bowel-pattern interpretation when combined with other symptoms, but it does not independently establish a disease or override explicit negatives and safety rules.
- Added Bristol type to deterministic screening evidence.
- Added `SUMMARY_REVIEW` to the API's deterministic response handling.
- Preserved existing NLU, question resolution, safety screening, diagnosis, and product recommendation modules.

## Verification

- `python -m compileall -q .`: passed.
- `node --check gutgpt-widget.js`: passed.
- Inline JavaScript syntax checks for `index.html` and `chat.html`: passed.
- Test suite excluding `tests/test_customer_json_registration.py`: 323 passed, 18 subtests passed.
- The excluded customer-registration test module could not be collected in this environment because `langchain_core` is not installed and package installation was unavailable. This is an environment limitation; that test module was not verified here.

## Deployment notes

Deploy the complete project folder so `symptom_summary.py`, the updated Python modules, frontends, widget, and Bristol image are all included. Verify both the standalone frontend and Shopify widget. A non-urgent assessment should show the summary before the final assessment; clicking a Bristol type should record that selected type in the conversation.
