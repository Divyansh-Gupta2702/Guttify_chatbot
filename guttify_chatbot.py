"""GutGPT language layer.

Clinical pattern selection is performed by clinical_rule_engine.py. Groq only
turns the structured result into a clear conversational answer.
"""
import os
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq
from recommendation_engine import products as ALL_PRODUCTS

_ALL_PRODUCT_NAMES = [p.get("product_name", "") for p in ALL_PRODUCTS if p.get("product_name")]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-20b"

RESPONSE_PROMPT_TEMPLATE = """
You are GutGPT, Guttify's gut-health assessment and product assistant.

Your job is to explain a STRUCTURED CLINICAL SCREENING RESULT that has already
been calculated by the deterministic rule engine. Do not change the result,
add a different condition, or invent missing facts.

The user wants useful diagnostic-style reasoning. Therefore, when a likely
condition/pattern is supplied, state it clearly as a PRELIMINARY / LIKELY
ASSESSMENT. Do not weaken every answer into a generic "I can't diagnose"
response. Do not present a chat assessment as a confirmed medical diagnosis.

Rules:
1. Use ONLY the supplied SCREENING RESULT for the clinical assessment.
2. Explain why the pattern was selected using the supplied evidence.
3. If differentials are supplied, mention the main alternatives briefly.
4. If confidence is low/insufficient, say that more information or medical
   assessment is needed instead of inventing certainty.
5. If the action is urgent_medical_evaluation, prioritize medical evaluation
   and do NOT recommend a product. If the action is medical_review and the
   rule engine supplied an approved product, present that product only as
   supportive wellness information after the medical-review guidance.
6. If product information is supplied, the product is allowed only because the
   rule engine explicitly allowed it. Present it after the assessment.
7. Never claim a product cures or treats a disease.
8. Never invent product facts, ingredients, dosage, warnings, price, links, or
   benefits. Use only CURRENT APPROVED PRODUCT.
9. Do not mention any Guttify product other than CURRENT APPROVED PRODUCT.
10. Do not diagnose a disease solely because a product exists for it.
11. Keep the answer clear and reasonably concise.
12. Do not append a generic wellness/medical disclaimer footer.

CONVERSATION HISTORY:
{conversation_history}

CURRENT USER MESSAGE:
{user_query}

SCREENING RESULT:
{screening_result}

CURRENT APPROVED PRODUCT:
{product_information}

FORMAT when a likely assessment exists:
Likely assessment: [condition/pattern]

Why:
- [evidence]

What this means:
[plain-English interpretation]

What to do next:
[action]

Possible alternatives:
[only if supplied and useful]

If a product is approved:
Guttify product that matches this assessment:
[product name]

[brief relevant product support]
[usage/warnings/link only from supplied product information]
"""

response_prompt = PromptTemplate(
    template=RESPONSE_PROMPT_TEMPLATE,
    input_variables=["conversation_history", "user_query", "screening_result", "product_information"],
)


def load_llm():
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Get a key at https://console.groq.com and set it as an environment variable."
        )
    return ChatGroq(model=GROQ_MODEL, temperature=0.1, max_tokens=700, api_key=GROQ_API_KEY)


def _bullets(items):
    return "\n".join(f"- {item}" for item in items)


def format_product_information(product):
    if not product:
        return "NO APPROVED PRODUCT."
    flavor_line = ""
    if product.get("flavors"):
        flavor_line = f"\nFlavors: {', '.join(product['flavors'])}"
    elif product.get("variants"):
        flavor_line = "\nVariants:\n" + "\n".join(
            f"- {v['flavor']}: {v['url']}" for v in product["variants"]
        )
    return (
        f"Product name: {product.get('product_name','')}\n"
        f"Category: {product.get('category','')}\n"
        f"Intended support:\n{_bullets(product.get('intended_support', []))}\n"
        f"Ingredients:\n{_bullets(product.get('ingredients', []))}\n"
        f"How to use: {product.get('how_to_use','')}\n"
        f"Warnings:\n{_bullets(product.get('warnings', []))}\n"
        f"Product link: {product.get('product_url','')}"
        f"{flavor_line}"
    )


def format_conversation_history(history):
    if not history:
        return "No previous conversation."
    return "\n".join(
        f"{'User' if m['role']=='user' else 'GutGPT'}: {m['content']}" for m in history
    )


def _mentions_unapproved_product(reply_text, approved_product):
    approved = approved_product.get("product_name") if approved_product else None
    low = reply_text.lower()
    return any(name.lower() in low for name in _ALL_PRODUCT_NAMES if name and name != approved)


def _deterministic_screening_reply(screening, product=None):
    if not screening:
        return "I need a little more information before I can assess the pattern."
    parts = [f"Likely assessment: {screening.get('likely_condition', screening.get('pattern', 'Insufficient information'))}"]
    evidence = screening.get("evidence") or []
    if evidence:
        parts += ["", "Why:"] + [f"- {x}" for x in evidence]
    parts += ["", "What to do next:", screening.get("message") or "Follow the next-step guidance from a healthcare professional if symptoms persist or worsen."]
    if screening.get("differentials"):
        parts += ["", "Possible alternatives:", ", ".join(screening["differentials"])]
    if product:
        parts += ["", f"Guttify product that matches this assessment:\n{product.get('product_name','')}"]
        if product.get("intended_support"):
            parts += ["", "Relevant support:", "- " + "\n- ".join(product["intended_support"][:4])]
        if product.get("how_to_use"):
            parts += ["", "How to use:", product["how_to_use"]]
        if product.get("warnings"):
            parts += ["", "Important warnings:", "- " + "\n- ".join(product["warnings"])]
        if product.get("product_url"):
            parts += ["", "Product link:", product["product_url"]]
    return "\n".join(parts)


def generate_response(llm, user_query, conversation_history, product=None, screening=None):
    history_text = format_conversation_history(conversation_history)
    screening = screening or {}
    product_info = format_product_information(product)
    prompt_text = response_prompt.format(
        conversation_history=history_text,
        user_query=user_query,
        screening_result=screening,
        product_information=product_info,
    )

    for attempt in range(2):
        if attempt:
            prompt_text += "\n\nCorrection: stay strictly within the supplied screening result and approved product."
        try:
            candidate = llm.invoke(prompt_text).content
            if not product or not _mentions_unapproved_product(candidate, product):
                return candidate
        except Exception:
            break
    return _deterministic_screening_reply(screening, product)


def chatbot():
    print("\n" + "=" * 60)
    print("                         GUTGPT")
    print("=" * 60)
    print("\nHi! I'm GutGPT, Guttify's gut-health assessment assistant.")
    llm = load_llm()
    history = []
    while True:
        user_query = input("\nYou:\n> ").strip()
        if user_query.lower() in ("exit", "quit", "bye"):
            print("\nThank you for using GutGPT.")
            break
        if not user_query:
            continue
        print("\nGutGPT is assessing your symptoms...")
        # CLI single-turn mode remains available for product lookup projects;
        # the web app uses ConversationManager for the full multi-turn flow.
        from recommendation_engine import recommend_product
        result = recommend_product(user_query)
        if result.get("status") in ("RECOMMENDATION_FOUND", "PRODUCT_INFO_FOUND"):
            product = result["recommendations"][0]
            answer = generate_response(llm, user_query, history, product, result.get("screening"))
        else:
            answer = result.get("message") or "Please provide more detail about your symptoms."
        print("\n" + answer)
        history.extend([{"role":"user","content":user_query},{"role":"assistant","content":answer}])
