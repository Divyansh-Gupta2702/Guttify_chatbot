# GutGPT Diagnosis Validation

## Scope

The diagnosis layer was reviewed across every primary symptom branch present in the current questionnaire and rule engine:

- Constipation / hard stools
- Diarrhea
- Acidity / heartburn
- Bloating / gas
- Stomach / abdominal pain
- Indigestion
- Food intolerance / food-triggered symptoms
- Piles / hemorrhoid pattern
- Anal fissure pattern
- Rectal bleeding
- IBS-C / IBS-D / IBS-M pattern logic
- Red-flag presentations

## Main logic changes

1. Explicit user negatives are retained as structured state (`constipation_explicit`, `diarrhea_explicit`).
2. A single Bristol 1–2 stool does not create constipation when the user explicitly denies constipation.
3. A high bowel frequency alone does not create diarrhea when there is no loose/watery stool evidence and the user denies diarrhea.
4. Primary symptom branches are evaluated before weak secondary bowel features.
5. IBS patterns require chronicity, recurrent abdominal pain related to bowel movements, a meaningful bowel-pattern change, and no warning features.
6. Rectal bleeding remains a separate decision tree; bleeding alone does not become piles or fissure.
7. Red flags always override diagnosis and product recommendation.
8. Product eligibility remains separate from clinical pattern selection.

## Validation

- Existing project tests: 79 passed
- New full diagnosis matrix tests: 21 passed
- Combined: **100 passed, 4 subtests passed**

The tests include contradictory combinations such as:

- bloating + no constipation + hard stool
- bloating + no constipation + low weekly frequency
- bloating + diarrhea
- acidity + hard stool
- indigestion + high stool frequency without loose stool
- IBS symptoms with warning features
- bright-red blood + sharp pain
- bright-red blood + painless lump
- bright-red blood without a distinguishing feature
- black/tarry stool
- every primary branch with a red flag
