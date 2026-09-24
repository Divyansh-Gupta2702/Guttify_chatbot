# GutGPT V6 — Clinical Assessment Flow

This version fixes the V5 conversation-state problems and makes the bot perform a real **preliminary clinical-pattern assessment** before product matching.

## What changed

### 1. Question-context memory
The agent stores the exact field behind the current question. Therefore:

- `How long has this been happening?` → `5 months` updates duration.
- `What is your age?` → `23` updates age only.
- `Have you noticed blood?` → `no` updates blood to false.
- `Do you feel incompletely emptied?` → `yes` updates incomplete evacuation.

Answers are not treated as new unrelated queries.

### 2. Full constipation branch
The constipation branch covers the requested screening areas:

- duration
- bowel movements/week
- hard/lumpy stool and straining
- incomplete evacuation
- bloating/abdominal pain and bowel-movement relationship
- blood
- sharp/severe anal pain
- unexplained weight loss
- vomiting/fever/severe swelling
- age
- water intake
- fibre intake
- medicines/supplements

It stops once the clinical engine has enough information, but it can continue through the full branch when important fields are still missing.

### 3. Pattern differentiation
Examples:

- hard/infrequent stools + straining → **Functional constipation pattern**
- chronic constipation + recurrent abdominal pain related to bowel movements → **IBS-C pattern**
- bright-red blood + sharp/tearing pain → **Possible anal fissure pattern**
- bright-red blood + painless lump/prolapse → **Possible hemorrhoid pattern**
- black/tarry stool → **Possible gastrointestinal bleeding / urgent evaluation**
- meal/lying-down heartburn + reflux symptoms → **Reflux/GERD-like symptom pattern**

### 4. Product layer is separate
Clinical reasoning runs first. Product eligibility is then applied with an explicit allow-list so generic products such as vitamin supplements do not win merely because their database row contains the word `constipation`.

### 5. No endless "I need more information"
There is a hard question limit. If the branch is still incomplete at the limit, GutGPT returns the best available preliminary assessment instead of looping.

## Run locally

CMD:

```cmd
set GROQ_API_KEY=YOUR_GROQ_API_KEY
uvicorn app:app --host 0.0.0.0 --port 8080
```

Open:

```text
http://127.0.0.1:8080
```

## Tests

Run from the project folder:

```cmd
pytest -q
```

The included conversation tests cover the exact failure shown in the mobile screenshot, constipation vs IBS-C, fissure vs hemorrhoid, black stool red flags, and reflux/product matching.

## Important behavior

GutGPT presents a **preliminary likely pattern**, not a confirmed medical diagnosis. The deterministic engine chooses the pattern; Groq is only used to explain the already-selected result conversationally.
