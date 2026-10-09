# GutGPT 1.0.3 – Natural Answer / Question-State Fix

## Fixed
- Legacy `constipation` questionnaire ID now uses the same contextual parser as `stool_straining`.
- Plain `no`, `yes`, and natural answers such as `no strain, only normal pooping` are interpreted against the active question instead of being treated as unrelated text.
- Bare `yes` to a combined hard-stool/straining question confirms constipation without inventing both sub-features.
- Added contextual handling for previously incomplete questionnaire fields: blood+mucus, vomiting+fever, reflux, timing, food triggers, and related multi-part questions.
- Added support for natural daily stool-frequency phrases such as `3 loose stools per day`.
- Added support for bare Bristol answers such as `4` when the Bristol question is active.
- Fixed `32 years of age` being incorrectly extracted as a symptom duration.
- Kept explicit negative answers authoritative so later generic NLU cannot turn them into positives.
- Added regression tests for the legacy constipation question and natural-language answers.

## Verification
- `133 passed, 18 subtests passed`
- No Python syntax errors in modified modules.

## Important behavior
- The bot does not impose a character limit on user answers.
- Ambiguous bare answers are not converted into unsupported clinical facts.
- The active questionnaire state remains authoritative until the pending question has a usable answer.
