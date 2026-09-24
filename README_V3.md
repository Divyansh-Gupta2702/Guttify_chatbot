# GutGPT V3 — clinical-style assessment + Guttify product flow

This version changes the bot from a question-collection/product-recommendation bot into a **clinical-style symptom assessment assistant**.

## New flow

```text
USER
  ↓
INTENT / SYMPTOM EXTRACTION
  ↓
RED-FLAG SCREEN
  ↓
ADAPTIVE CLINICAL QUESTIONS
  ↓
DETERMINISTIC PATTERN ENGINE
  ↓
LIKELY ASSESSMENT + EVIDENCE + DIFFERENTIALS
  ↓
NEXT BEST ACTION
  ↓
PRODUCT ELIGIBILITY
  ↓
GUTTIFY PRODUCT (only when allowed)
  ↓
FOLLOW-UP / CHAT CLOSE
```

## What changed

- GutGPT now produces a **Likely assessment** instead of only collecting symptoms.
- The rule engine distinguishes patterns such as:
  - Functional constipation
  - IBS-C pattern
  - IBS-D pattern
  - Medication-associated constipation
  - Reflux/GERD-like symptoms
  - Dyspepsia/indigestion
  - Food-triggered symptoms
  - Possible anal fissure pattern
  - Possible hemorrhoid pattern
  - Recent-infection/food-related diarrhea
  - Nonspecific abdominal-pain pattern
- IBS-C/IBS-D classification requires a longer symptom history and relevant symptom pattern rather than simply seeing the words "constipation" or "diarrhea".
- Rectal bleeding is **not automatically called piles**. Bright-red bleeding plus sharp/tearing pain is handled as a possible fissure pattern; bright-red bleeding with a painless lump/prolapse is handled as a possible hemorrhoid pattern; black/tarry stool is escalated.
- Product recommendation happens only after the clinical-style assessment and only where the rule engine marks it as appropriate.
- Groq is now a **language/explanation layer**, not the decision-maker.
- The visible generic disclaimer footer has been removed.
- The UI uses **GutGPT**.

## Important implementation note

The assessment is a screening/clinical-style interpretation of chat information, not a substitute for a clinician's examination or testing. The code deliberately uses wording such as **Likely assessment** and **Possible pattern** where appropriate rather than pretending that a chat has confirmed a medical diagnosis.

Before production use, the medical/product team should review and approve the rule thresholds, questions, red flags, and product eligibility rules.

## Run

```cmd
pip install -r requirements.txt
set GROQ_API_KEY=YOUR_GROQ_KEY
uvicorn app:app --host 0.0.0.0 --port 8080
```

Open:

```text
http://127.0.0.1:8080
```

Do not use `http://0.0.0.0:8080` in the browser.
