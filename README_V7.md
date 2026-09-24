# GutGPT V7 — Clinical Assessment + Product Routing

## What changed

V7 keeps clinical-pattern reasoning separate from product eligibility, while restoring product recommendations for the full product catalogue.

### Clinical gut branches
- Functional constipation
- IBS-C / IBS-D / IBS-M pattern screening
- Reflux/GERD-like symptoms
- Dyspepsia/indigestion
- Gas/bloating
- Possible anal fissure pattern
- Possible hemorrhoid pattern
- Rectal bleeding of unclear cause
- Diarrhea / infection-related diarrhea
- Abdominal pain

### Product-specific concerns
These are routed to products without pretending they are medical diagnoses:
- Dull/dry/uneven skin → GloLux
- B12 deficiency, low energy, brain fog, plant-based diet → Boost Vitamin B12
- Vitamin D deficiency, low immunity, weak bones, low sun exposure → Boost Vitamin D3+
- Weight-management / metabolism support → Apple Active
- Liver support / sluggishness / digestive concerns → Liver Lift
- Low fibre intake → Guttify Poopie

### Gut product mapping
- Constipation / IBS-C / constipation-associated bloating → Digest Boost / Guttify Poopie
- Reflux/GERD-like symptoms / dyspepsia → Acid Ease
- Possible hemorrhoid pattern → Piles Pure / Piloease Anal Care Spray
- Possible anal fissure pattern → Piloease Anal Care Spray

## Safety behavior
- Black/tarry stool, vomiting blood, severe abdominal pain, persistent vomiting, severe distension, fainting, dehydration, significant unexplained weight loss, persistent fever, difficulty swallowing, inability to pass stool and gas, etc. stop product recommendation and trigger medical evaluation.
- Bright-red rectal bleeding is not automatically treated as piles. The bot asks distinguishing questions before selecting a possible fissure or hemorrhoid pattern.
- Confirmed disease diagnosis is not claimed; outputs are preliminary/likely assessments based on the conversation.

## Verification
Run:

```cmd
python -m pytest -q
```

V7 currently has 49 passing automated tests covering conversation state, clinical patterns, red flags, product routing, and regression cases.
