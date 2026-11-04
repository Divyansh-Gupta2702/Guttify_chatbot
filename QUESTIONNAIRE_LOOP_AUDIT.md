# GutGPT v18.4 Questionnaire Loop Audit

## Dependency map and this revision's pre-edit findings (2026-11-04)

### Data and rendering path

```text
gutgpt-widget.js customer intake (/api/customer)
  -> PostgreSQL customers.age
  -> /api/customer/restore binds authenticated customer and seeds in-memory SymptomState.age
  -> /api/customer/resume -> _restore_assessment_checkpoint(customer_id, session_id)
  -> assessment_state.checkpoint JSONB -> SessionState / SymptomState
  -> ConversationManager.handle_message
     -> extract_natural_facts (NLU extraction)
     -> resolve_against_active_question (question_schema.py)
     -> _apply_answer / state merge (guttify_agent.py + intent_parser.py)
     -> next_question (symptom_questionnaire.py; question ownership in question_schema.py)
     -> evaluate_screening (clinical_rule_engine.py)
     -> check_safety / red-flag gates (safety_checker.py)
     -> PRODUCT_ELIGIBILITY + recommendation_engine.py / products.json
  -> /api/chat result text (including [[BRISTOL_STOOL_CHART]] display marker)
  -> assessment_messages.content + assessment_state.checkpoint in PostgreSQL
  -> widget addMessage -> renderMarkdown -> Bristol image and type buttons in Shadow DOM
```

`question_schema.py` maps stable question IDs to owned `SymptomState` fields and
answer kinds; `symptom_questionnaire.py` chooses one active question based on
primary symptom, known state and safety priority. `clinical_rule_engine.py`
contains the deterministic 27 outcome patterns. `safety_checker.py` gates the
same screening result before `PRODUCT_ELIGIBILITY` and recommendation matching.
Customer identity/profile fields live in PostgreSQL `customers`; assessment
transcripts and checkpoints live in `assessment_messages` and `assessment_state`.

### Confirmed findings before implementation

- **Combined questions:** `next_question()` still emits compound prompts in
  constipation, diarrhea, stomach-pain, indigestion, food-intolerance, and
  fallback branches. The corresponding legacy IDs in `QUESTION_SCHEMA` own
  multiple clinical fields. Although the contextual resolver can extract
  components, an incomplete answer keeps the entire composite active and
  requires clarification. This is the source of ambiguity/repetition and does
  not satisfy one-independent-field-per-question.
- **Age restoration:** registration and `/api/customer/restore` seed age from
  the customer profile, but `_restore_assessment_checkpoint()` reconstructs the
  assessment checkpoint without reapplying the authoritative `customers.age`.
  A checkpoint with a null/stale age can therefore ask for age again after
  resume. The checkpoint writer serializes the current `SymptomState`, so a
  corrected age can also be present in assessment state without updating the
  authoritative customer profile.
- **Bristol rendering:** the stool question carries a marker in message text;
  the widget replaces it with an embedded data URI. The embedded bytes start
  with JPEG magic (`FF D8`) but are declared as `data:image/png`, while the
  repository asset is a separate PNG. The marker-to-image behavior is therefore
  coupled to a large mislabeled inline image, with no asset endpoint or image
  load fallback. Resume replays assistant message content, so it can restore the
  marker, but there is no server-owned render metadata or verified asset URL.
- **Question state / shared questions:** `asked_fields` is intentionally only a
  history; `question_has_progressed()` and `last_question` control completion.
  Composite ownership currently makes shared concepts hard to reuse atomically.
  Existing safety unknown/refusal tracking and bleeding-priority routing must
  remain in force when questions are split.

These findings were recorded before code changes. This revision will retain
legacy question IDs and resolver mappings for old checkpoints, and add atomic
IDs for the newly separated prompts; no table or record deletion is required.

## Scope and inventory

- Source of truth: questionnaire selectors, schema ownership/completion, deterministic NLU resolver, state merge, rule engine, safety checker, checkpoint restore/save, and tests in this checkout.
- Pre-edit baseline: 38 question IDs were active in `symptom_questionnaire.py`; 18 active IDs had compound/multi-field semantics. The ownership table below documents that baseline; the revised active selectors now emit atomic IDs for those separated prompts, while retaining legacy schema IDs for stored checkpoints.
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

## Implementation and verification (2026-11-04)

- Split the active compound prompts into individually owned questions, including stool hardness vs straining, blood vs mucus, pain vs pain/bowel relation, and separate fever, vomiting, distension, swallowing, and night-symptom checks. Legacy IDs remain mapped for old checkpoint compatibility. The question ceiling is now 30 to allow the additional individual follow-ups.
- Restored assessment age is overlaid from `customers.age` after checkpoint reconstruction, with the profile value validated to 1–120. A valid user correction updates `customers.age` and `updated_at`; on a failed write for a bound customer, the in-memory age is reverted and the chat returns HTTP 503.
- Added `/bristol-stool-chart.png` serving the existing repository PNG as `image/png`. The widget loads that hosted asset, falls back to the embedded JPEG with the correct MIME type, and hides the image if both loads fail.
- Kept the deterministic rule engine, 27 outcome patterns, safety gates, recommendations, authentication, and PostgreSQL persistence model. No schema migration or production deployment was performed.
- Full local test suite: **588 passed, 8 skipped, 28 subtests passed**. The skipped tests require a disposable PostgreSQL/Groq integration environment (`GROQ_TEST_DATABASE_URL`); no live PostgreSQL integration was run.
- The Bristol route function and repository PNG signature are covered locally, and widget source fallback behavior is covered. A running HTTP server, production HTTPS origin, Shopify storefront rendering, and customer restore against live PostgreSQL were not available for end-to-end verification.
- Deployment/rollback: deploy the reviewed commit to the existing API service and restart that service using its configured systemd unit; the repository does not identify the production host or unit name, so an exact host-specific restart command cannot be substantiated here. No database migration is required. For rollback, restore the prior application revision and restart the same unit; the previous widget can continue using its embedded chart. Do not deploy until the production service/unit and normal release procedure are confirmed.

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
