# GutGPT v18.2 Pain-question fix

Fixed a questionnaire semantic bug for the `pain` question.

## Previous behavior

For a question such as:

> Do you have recurring abdominal pain that changes with bowel movements?

- `yes` was left unresolved because the legacy parser intentionally skipped bare yes for all composite questions.
- `I do have some pain` was recognized as abdominal pain but the bot repeated the entire question instead of asking only for the missing bowel-movement relationship.

## v18.2 behavior

`pain` is now represented as a conjunctive proposition rather than an ambiguous OR-style composite question:

- `yes` -> `abdominal_pain=True`, `pain_related_to_bowel_movement=True`
- `no` -> `abdominal_pain=False`, `pain_related_to_bowel_movement=False`
- `I do have some pain` -> `abdominal_pain=True`, relation remains unresolved and the bot asks:
  `Does the pain improve, worsen, or change after you have a bowel movement?`
- A later `yes` resolves the relation and advances to the next questionnaire field.

This does not change the semantics of ambiguous composite questions such as `Any vomiting, fever, or severe swelling?`, where a bare `yes` remains unresolved.

## Verification

227 tests passed, 18 subtests passed.
