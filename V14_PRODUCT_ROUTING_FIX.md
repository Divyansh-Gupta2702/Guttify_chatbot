# v14 Product Routing Fix

## Changes

1. Food-triggered intolerance patterns are now diagnosis-only because the current product database has no product explicitly intended for food intolerance.
   - `Possible food-triggered intolerance pattern` -> `product_allowed=False`
   - `Possible food-triggered symptom pattern` -> `product_allowed=False`

2. Ambiguous product matches no longer need a tie-breaking question.
   - All equally suitable approved products are returned together.
   - The response explains each product's intended support/use case.
   - The user chooses the product that best fits their goal.

3. Existing safety checks, clinical diagnosis rules, NLU flow, and product allow-lists remain intact.

## Validation

- 155 pytest tests passed
- 18 subtests passed
