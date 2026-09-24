# GutGPT V4 — Clinical-pattern assessment fix

This version fixes the two major V3 failure modes:

1. The bot no longer treats every answer as a fresh standalone message. Each answer is mapped to the question that was asked, so `no`, `yes`, ages, durations, stool descriptions, bleeding details, etc. update the correct field.
2. The original symptom branch is preserved. Saying `I also have abdominal pain` no longer changes a constipation conversation into a bloating/stomach-pain branch.
3. The bot stops asking when there is enough information for a preliminary clinical pattern.
4. It does not repeatedly return `I need more information` after the questionnaire limit.
5. Chronic constipation is checked for an IBS-C pattern before being labelled functional constipation.
6. Rectal bleeding is differentiated using colour + pain + lump/prolapse rather than automatically calling it piles.
7. A clinical assessment is shown before product ambiguity can hide the result.
8. The product engine remains downstream from clinical-pattern reasoning.

Examples of expected assessments:

- Hard/infrequent stools + straining/incomplete evacuation -> Functional constipation pattern
- Chronic constipation + recurrent abdominal pain related to bowel movements -> IBS-C pattern
- Bright-red blood + sharp/tearing pain during stool -> Possible anal fissure pattern
- Bright-red blood + no sharp pain + lump/prolapse -> Possible hemorrhoid pattern
- Heartburn/acidity + meal/night association -> Reflux/GERD-like symptom pattern

The assessments are preliminary screening patterns, not confirmed medical diagnoses. A confirmed diagnosis may require a clinician's history, examination and/or tests.

## Run on Windows CMD

```cmd
set GROQ_API_KEY=YOUR_GROQ_API_KEY
uvicorn app:app --host 0.0.0.0 --port 8080
```

Open:

```text
http://127.0.0.1:8080
```


## V5 fixes
- Recognizes natural constipation phrases such as "unable to pass my stools".
- Keeps an active question context so answers like "5 months" are never classified as irrelevant.
