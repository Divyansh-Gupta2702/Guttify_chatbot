# GutGPT v18.4 Questionnaire Loop Audit

## Scope and inventory

- Source of truth: questionnaire selectors, schema ownership/completion, deterministic NLU resolver, state merge, rule engine, safety checker, checkpoint restore/save, and tests in this checkout.
- 38 question IDs are active in `symptom_questionnaire.py`; the schema owns 45 IDs, including legacy and non-question entries. 18 active IDs have compound/multi-field semantics.
- The rule engine returns 27 distinct clinical outcome patterns. Outcomes share questionnaire branches; they are not separate question trees.
- Active state persists through `SessionState` dataclass serialization into the existing JSONB PostgreSQL checkpoint. New resolver metadata uses existing state fields; no DB migration was added.

## Active question ownership inventory

| Question ID | Deterministic state fields | Answer type |
|---|---|---|
| `age` | `age` | numeric |
| `anal_pain` | `anal_pain`, `sharp_pain_during_stool` | boolean |
| `bloating_pain` | `abdominal_pain`, `bloating`, `pain_related_to_bowel_movement` | composite_boolean |
| `blood` | `blood_present` | boolean |
| `blood_colour` | `blood_colour` | choice |
| `blood_location` | `blood_location` | choice |
| `blood_mucus` | `blood_present`, `mucus` | composite_boolean |
| `bowel_frequency` | `bowel_frequency_per_week` | numeric |
| `bowel_pattern` | `constipation_explicit`, `diarrhea`, `diarrhea_explicit` | choice |
| `constipation` | `constipation_explicit`, `hard_stools`, `stool_form`, `straining` | composite_boolean |
| `daily_frequency` | `bowel_frequency_per_day` | numeric |
| `duration` | `duration` | duration |
| `fibre` | `fibre_intake` | choice |
| `food_relation` | `food_related` | boolean |
| `food_trigger` | `food_related`, `food_trigger` | choice |
| `incomplete_evacuation` | `incomplete_evacuation` | boolean |
| `infection` | `recent_infection` | boolean |
| `lump` | `lump_or_prolapse` | boolean |
| `medications` | `medications` | free_text |
| `night_weight_fever` | `fever`, `night_time_symptoms`, `weight_loss` | composite_boolean |
| `pain` | `abdominal_pain`, `pain_related_to_bowel_movement` | conjunctive_boolean |
| `pain_location` | `pain_location` | choice |
| `pain_relation` | `food_related`, `pain_related_to_bowel_movement` | choice |
| `reflux` | `reflux_present` | boolean |
| `severity` | `severity` | numeric |
| `stool_form` | `stool_form` | numeric |
| `stool_straining` | `constipation_explicit`, `hard_stools`, `stool_form`, `straining` | composite_boolean |
| `swallowing` | `difficulty_swallowing`, `persistent_vomiting`, `vomiting_blood` | composite_boolean |
| `symptoms` | `abdominal_pain`, `bloating`, `constipation_explicit`, `diarrhea`, `gas`, `other_symptoms` | free_text |
| `timing` | `meal_timing`, `symptom_onset_after_food`, `timing_relation` | timing |
| `trigger` | `food_related`, `food_trigger` | choice |
| `triggers` | `food_related`, `food_trigger` | choice |
| `upper_symptoms` | `upper_symptoms` | free_text |
| `vomiting_fever` | `fever`, `vomiting` | composite_boolean |
| `vomiting_fever_swelling` | `abdominal_distension`, `fever`, `vomiting` | composite_boolean |
| `water` | `water_intake` | numeric |
| `weight_loss_duration` | `weight_loss` | boolean |
| `weight_swallow` | `difficulty_swallowing`, `persistent_vomiting`, `vomiting_blood`, `weight_loss` | composite_boolean |

## Pattern-to-questionnaire branch audit

| Questionnaire branch | Outcomes served by the existing rule engine | Required/question groups and important conditions |
|---|---|---|
| Constipation | Functional constipation; medication-associated constipation; IBS-C; constipation-associated bloating | Duration and age; weekly frequency; stool hardness/straining; incomplete evacuation; bloating/pain and bowel relation when pain is present; bleeding and anal-pain checks; vomiting/fever/distension; water, fibre, medication. Weight-loss question is conditional on longer duration. |
| Diarrhea | Diarrhea; recent-infection or food-related diarrhea; IBS-D/IBS-M when bowel pattern and pain criteria support them | Duration/age; daily loose-stool count; optional Bristol type (unknown accepted); pain and bowel relation; infection/food context; blood/mucus; night symptoms/weight loss/fever; medication. |
| Acidity/reflux | Reflux/GERD-like symptoms | Reflux; meal/position/night timing; food triggers; swallowing, persistent vomiting, and vomiting blood safety components. |
| Bloating/gas | Functional gas/bloating; food-triggered gas/bloating; constipation-associated bloating | Bowel pattern; recurring food trigger; pain and bowel relation if pain is reported; optional stool form when applicable. |
| Stomach/abdominal pain | Bowel-related abdominal pain; nonspecific abdominal pain; red-flag presentation | Pain location and severity/worsening; meal vs bowel relation; bowel pattern; vomiting/fever; safety-derived red flags. |
| Indigestion | Dyspepsia/indigestion; upper-abdominal meal-related dyspepsia | Upper-GI symptom description; meal relation; reflux follow-up only when heartburn is present; weight loss/swallowing/vomiting safety group. |
| Food intolerance / food-triggered symptoms | Possible food-triggered intolerance; possible food-triggered symptom pattern | Repeated trigger; onset timing; symptom category (bloating, gas, diarrhea, cramps, constipation, or other). |
| Anal symptoms / bleeding | Possible fissure; possible hemorrhoid; anal irritation/burning; anal swelling/lump; insufficiently characterized anal pattern; bleeding patterns; possible GI bleeding | Bleeding is prioritized. Blood colour/location activate only when blood is present; anal pain/lump/constipation distinctions are conditional to the branch. Red flags override ordinary completion. |
| Fallback / safety | Insufficiently characterized gut symptom pattern; red-flag presentation | Existing red-flag checker and rule engine take priority. Unknown/refused safety answers produce incomplete safety review, never a negative finding or product recommendation. |

## Confirmed and potential loop conditions

### Confirmed and fixed

- Compound answers such as “I have a fever,” “No blood,” and “Yes, vomiting” were all-or-nothing or did not retain their explicit component. The resolver now saves each deterministic component and asks only the missing component.
- “I have abdominal pain” could be interpreted as a bare yes to the relationship question and fabricate bowel-movement association. Bare yes is now scoped to an explicitly focused component; pain alone remains partial.
- Daily counts with a modifier (“3 loose stools per day”) did not match the numeric pattern and repeated `daily_frequency`. The deterministic parser now accepts this form without Groq.
- Negative multi-part replies could leave the abdominal-distension or persistent-vomiting component unset. Component mappings now resolve explicit negatives independently.
- `upper_symptoms` was owned by `abdominal_pain`, so valid “nausea/fullness” replies could not satisfy the question. It now has a dedicated context field. The open-ended `symptoms` question now accepts gas and verbatim other symptoms.
- Pain-positive answers to the constipation bloating/pain disjunction were still forced to answer bloating after the pain and bowel relationship were known. Completion now follows the prompt’s disjunction without asserting that bloating is absent.
- Active-state merge could erase unknown/refusal component metadata. These status fields are preserved independently from clinical values.
- A previously negated bleeding fact could not be updated by an explicit volunteered correction while another question was active. Explicit bleeding mentions now update the state; conditional bleeding follow-ups activate after the still-pending active question is answered.
- A stale checkpoint assessment ID owned by another customer could pass through `ON CONFLICT DO NOTHING`, leaving the current customer's checkpoint aimed at an ID it did not own. The writer now checks ownership and allocates a fresh ID on a collision.
- Repeated identical unrelated answers no longer advance by a fixed clarification count. Required questions remain pending and clarification is targeted to the missing component.

### Potential risks audited and retained as gates

- Unknown/refused red-flag answers are tracked separately from clinical booleans and block diagnosis/product completion pending clinical review.
- Conditional follow-ups remain driven by the existing state predicates; a correction to blood activates blood discriminators, while a corrected negative clears blood-only colour/location fields.
- Previously collected unrelated facts are restored during active-question merges; explicit values from the current answer can correct their matching field.
- PostgreSQL checkpoint round-trip uses `asdict(SessionState)` and reconstructs both `SessionState` and `SymptomState`; new component/status fields therefore require no schema migration.

## Rule-engine outcomes inventoried

- Anal irritation/burning symptom pattern
- Anal swelling/lump symptom pattern
- Bowel-related abdominal pain pattern
- Constipation-associated bloating pattern
- Diarrhea pattern
- Dyspepsia/indigestion pattern
- Food-triggered gas/bloating pattern
- Functional constipation pattern
- Functional gas/bloating pattern
- IBS-C pattern
- IBS-D pattern
- IBS-M (mixed) pattern
- Insufficiently characterized anal-symptom pattern
- Insufficiently characterized gut symptom pattern
- Nonspecific abdominal pain pattern
- Possible anal fissure pattern
- Possible food-triggered intolerance pattern
- Possible food-triggered symptom pattern
- Possible gastrointestinal bleeding
- Possible hemorrhoid pattern
- Possible medication-associated constipation pattern
- Recent-infection or food-related diarrhea pattern
- Rectal bleeding of unclear cause
- Rectal bleeding — pattern not yet distinguishable
- Red-flag presentation
- Reflux/GERD-like symptom pattern
- Upper-abdominal meal-related dyspepsia pattern

## Verification and limitations

- Conversation-level simulation walks all 10 existing supported primary symptom branches. It fails on a repeated pending state fingerprint and on a resolved question being selected again; it does not rely on a fixed question-count cutoff. A separate 27-case rule-engine matrix verifies every inventoried outcome remains reachable.
- The full suite is run with `python -m pytest -q --basetemp <workspace-temp>`.
- Eight PostgreSQL/Groq integration cases require `GROQ_TEST_DATABASE_URL` to point to a disposable PostgreSQL database; they are skipped when that environment variable is absent. In this run they were not exercised against a real PostgreSQL service.
- Several of the 27 rule-engine outcomes intentionally share questionnaire branches; the end-to-end simulator covers each of the 10 branch trees, and the matrix covers the individual outcome rules.
