# GutGPT V8 – Clinical Product Flow FIXED V7

## V7 conversation-state fix

- A completed clinical assessment is now terminal for diagnosis within the current session.
- The terminal state is set as soon as an assessable clinical pattern is reached, including when a product recommendation is returned.
- Later symptom messages return `DIAGNOSIS_COMPLETE` instead of restarting the questionnaire or generating another diagnosis.
- Named product lookups remain available after diagnosis.
- Thank-you/gratitude messages never end or lock the chat, including common variants such as `thanks, got it`, `ok thanks`, `thank you very much`, and `much appreciated`.
- Only explicit stop/end/cancel commands close the chat and trigger the existing feedback flow.

## Verification

`78 passed, 6 subtests passed`
