# GutGPT Gemini migration and expanded assistant

## What changed

- Gemini is the configured default provider (`GUTGPT_LLM_PROVIDER=gemini`). The existing provider adapter, bounded invocation guard, request budget, concurrency control, circuit breaker and one-time Gemini fallback are retained.
- Gemini primary model: `gemini-3.8-flash`; fallback: `gemini-3.1-flash-lite`. Both IDs are listed in Google's current Gemini API model catalogue. Keep model IDs configurable in the server environment.
- Added validated intent labels for general knowledge, Guttify/company information and scientific research summaries.
- General knowledge uses a restricted assistant prompt. It answers ordinary educational questions, but cannot diagnose, prescribe/dose medication, override clinical safety, or make product claims.
- Company information is grounded in `company_knowledge.py`, which contains facts reviewed from the official Guttify website, and in the existing `products.json` catalogue. Unknown policies, offers, stock, shipping and changing prices are not guessed.
- Research questions use bounded PubMed E-utilities retrieval (up to four records), including abstracts when available. The model must summarize only retrieved abstracts and cite retrieved PubMed records. Retrieval failure returns a clear fallback.
- Feature flags allow the three new capabilities to be disabled independently.
- The brittle hard-coded list of unrelated keywords was removed. Clinical safety checks and deterministic assessment logic remain in their existing order.
- No changes were made to clinical diagnosis/rule files, product eligibility, product catalogue schema, PostgreSQL persistence, JWT/session lifecycle or Shopify widget contract.

## Required production configuration

Set these on the DigitalOcean server's actual systemd EnvironmentFile (discover it with `systemctl cat <service-name>`):

```dotenv
GUTGPT_LLM_PROVIDER=gemini
GEMINI_API_KEY=your-server-side-key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite
GEMINI_TIMEOUT_SECONDS=12
GEMINI_PAID_TIER_CONFIRMED=true
GUTGPT_GENERAL_KNOWLEDGE_ENABLED=true
GUTGPT_COMPANY_KNOWLEDGE_ENABLED=true
GUTGPT_RESEARCH_ASSISTANT_ENABLED=true
GUTGPT_RESEARCH_TIMEOUT_SECONDS=5
```

**Production privacy requirement:** `GEMINI_PAID_TIER_CONFIRMED=true` is required by startup validation when Gemini is selected. Set it only after the Google Cloud project used by this API key has active billing / Paid Tier. Google's current Gemini API pricing and terms say Free Tier content may be used to improve Google products, while Paid Tier prompts and responses are not used for that purpose. Do not send customer health conversations to a Free Tier project. Paid Tier still has limited abuse-monitoring retention; this is not a zero-data-retention guarantee. Review Google's current terms and privacy obligations before production use.

The API key must remain on the server. Never put it in `gutgpt-widget.js`, Shopify theme code or browser JavaScript.

## Deployment and rollback

1. Back up the currently deployed source and the PostgreSQL database before release.
2. Upload the updated source tree, including `company_knowledge.py`, `research_assistant.py`, and this document.
3. Install dependencies from `requirements.txt` in the server's existing virtual environment. `google-genai` is already included in the supplied requirements.
4. Set the Gemini variables above in the existing systemd EnvironmentFile. Confirm the selected Google project is on Paid Tier before setting the confirmation flag.
5. Run the full test suite on the server before restart. Check `python -m py_compile` on changed Python modules.
6. Restart the actual GutGPT systemd service and inspect `journalctl -u <service-name> -n 150 --no-pager`.
7. Test a general knowledge question, a Guttify company question, a named product question, a research question, a normal symptom assessment, an explicit red-flag disclosure, and a follow-up during an active questionnaire.
8. Roll back by restoring the source backup and setting `GUTGPT_LLM_PROVIDER=groq` with a valid `GROQ_API_KEY`, then restart. Keep Groq dependencies and credentials until Gemini has passed production regression testing.

## Known limitations / follow-up work

- Company facts are a curated snapshot of public pages, not a live Shopify crawler. Prices, offers, shipping, return/refund details and inventory are deliberately not cached as facts. Review and update `company_knowledge.py` when official pages change.
- Product facts are sourced from `products.json`; reconcile it with current Shopify product pages before claiming it is fully synchronized.
- PubMed retrieval is a lightweight search-and-summary feature, not a systematic review or clinical decision support tool. It may return only metadata/abstracts, and the user should open the linked paper for full methods/results. It does not prove that a Guttify product works.
- The uploaded code snapshot's test run in the build environment is limited because `langchain_core` is not installed and outbound package installation is unavailable. See the handoff summary for exact test results.
