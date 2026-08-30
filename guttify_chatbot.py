"""Guttify AI Assistant — conversational product recommendation chatbot."""
import os

from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq

from recommendation_engine import recommend_product

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
# llama-3.1-8b-instant has a much higher free-tier daily request cap
# (~14,400/day) than the 70b models (~1,000/day), which matters more for
# sustaining live traffic than the small quality gap between them. Swap to
# "llama-3.3-70b-versatile" if you want stronger answers and your traffic
# is light enough to stay under its lower daily cap.
GROQ_MODEL = "llama-3.1-8b-instant"

RESPONSE_PROMPT_TEMPLATE = """
You are Guttify's product-focused assistant.

You are NOT a doctor, and you are NOT a general-purpose chatbot — you only
answer questions about Guttify products, gut-health symptoms, and product
recommendations.

IMPORTANT RULES:
1. Do not diagnose diseases.
2. Do not claim that a Guttify product cures or treats a disease.
3. Do not invent products, ingredients, benefits, dosages, warnings,
   prices, specifications, certifications, or links.
4. Only use the supplied product information, including the product link.
5. If the user asks about something not present in the supplied product
   information (for example, price, if none is given), say plainly:
   "I don't have this information in the available product details."
   Do not guess.
6. If an approved product is supplied, do not replace it with another
   product, and do not recommend additional products.
7. Ask a useful follow-up question only when no product information was
   supplied and the user's concern is still unclear.
8. Do not repeatedly ask the user for information they already provided.
9. Use the conversation history to understand words such as "it", "this",
   "that", "also", and "again".
10. Keep responses concise and conversational.
11. If the user appears to have a serious, worsening, or concerning
    situation, encourage them to seek appropriate medical care.
12. A product recommendation is a wellness recommendation and is not a
    medical diagnosis or treatment.
13. If a product link is supplied, include it exactly as given. If none is
    supplied, omit the link line entirely rather than making one up.
14. If the user asked about only one specific aspect of a product (for
    example, just its ingredients, just how to use it, or just its
    warnings), answer that specific question directly and briefly. You do
    NOT need to use the full format below unless the user asked for a
    full recommendation or overview.

CONVERSATION HISTORY:
{conversation_history}

CURRENT USER MESSAGE:
{user_query}

CURRENT APPROVED PRODUCT:
{product_information}

INSTRUCTIONS:

If an approved product is available and the user asked for a full
recommendation or overview, use this format:

Recommended Guttify Product:
[Product name]

Why it may be relevant:
[Concise explanation]

What it supports:
[Relevant intended support]

How to use:
[Usage information]

Important warnings:
[Relevant warnings]

Product link:
[Exact product link, only if one is supplied]

Flavor options:
[List flavors or flavor-specific links, only if supplied — otherwise omit this section]

Disclaimer:
[Short wellness disclaimer]

If the user asked about only one specific aspect of the product (see rule
14), skip this format entirely and just answer that one aspect directly,
using only the supplied product information.

If NO approved product is available, do NOT invent or recommend a
product. Instead, respond conversationally and ask one useful follow-up
question that can help understand the user's concern better.
"""

response_prompt = PromptTemplate(
    template=RESPONSE_PROMPT_TEMPLATE,
    input_variables=["conversation_history", "user_query", "product_information"],
)


def load_llm():
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com "
            "and set it as an environment variable before running this app."
        )
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=0.3,
        max_tokens=512,
        api_key=GROQ_API_KEY,
    )


def _bullets(items):
    return "\n".join(f"- {item}" for item in items)


def format_product_information(product):
    if not product:
        return "NO APPROVED PRODUCT AVAILABLE."

    flavor_line = ""
    if product.get("flavors"):
        flavor_line = f"\n\nAvailable flavors:\n{', '.join(product['flavors'])}"
    elif product.get("variants"):
        variant_lines = "\n".join(f"- {v['flavor']}: {v['url']}" for v in product["variants"])
        flavor_line = f"\n\nFlavor options (each with its own link):\n{variant_lines}"

    return (
        f"Product name:\n{product.get('product_name', '')}\n\n"
        f"Category:\n{product.get('category', '')}\n\n"
        f"Intended support:\n{_bullets(product.get('intended_support', []))}\n\n"
        f"Ingredients:\n{_bullets(product.get('ingredients', []))}\n\n"
        f"How to use:\n{product.get('how_to_use', '')}\n\n"
        f"Warnings:\n{_bullets(product.get('warnings', []))}\n\n"
        f"Product link:\n{product.get('product_url', 'Not provided')}"
        f"{flavor_line}\n\n"
        f"Age group:\n{product.get('age_group', 'Not specified')}"
    )


def format_conversation_history(conversation_history):
    if not conversation_history:
        return "No previous conversation."

    return "\n".join(
        f"{'User' if m['role'] == 'user' else 'Guttify Assistant'}: {m['content']}"
        for m in conversation_history
    )


def generate_response(llm, user_query, conversation_history, product):
    final_prompt = response_prompt.format(
        conversation_history=format_conversation_history(conversation_history),
        user_query=user_query,
        product_information=format_product_information(product),
    )
    return llm.invoke(final_prompt).content


def print_banner(title, width=60):
    print("\n" + "=" * width)
    print(title)
    print("=" * width)


def display_safety_response(result):
    print_banner("                 SAFETY REVIEW")
    print("\n" + result["safety"]["message"])
    print("\nReasons:")
    for reason in result["safety"]["reasons"]:
        print(f"- {reason}")


def chatbot():
    print_banner("          GUTTIFY AI ASSISTANT")
    print("\nHi! I'm Guttify's product recommendation assistant.")
    print("Tell me what you're experiencing.")
    print("\nType 'exit' to quit.")

    print("\nLoading Guttify AI assistant...")
    llm = load_llm()
    conversation_history = []

    while True:
        print("\n" + "-" * 60)
        user_query = input("\nYou:\n> ").strip()

        if user_query.lower() in ("exit", "quit", "bye"):
            print("\nThank you for using Guttify AI Assistant.")
            break

        if not user_query:
            print("\nPlease tell me what you're experiencing.")
            continue

        print("\nAnalyzing your request...")
        result = recommend_product(user_query)
        status = result["status"]

        if status == "GIBBERISH":
            answer = result["message"]
            print("\n" + answer)

        elif status == "IRRELEVANT":
            answer = result["message"]
            print("\n" + answer)

        elif status == "SAFETY_REVIEW":
            display_safety_response(result)
            answer = result["safety"]["message"]

        elif status in ("RECOMMENDATION_FOUND", "PRODUCT_INFO_FOUND"):
            print("\nGenerating response...")
            best_product = result["recommendations"][0]
            answer = generate_response(llm, user_query, conversation_history, best_product)
            print_banner("                 GUTTIFY")
            print("\n" + answer)

        else:  # NO_MATCH
            print("\nI need a little more information to understand your concern.")
            answer = generate_response(llm, user_query, conversation_history, None)
            print("\nGuttify Assistant:")
            print("\n" + answer)

        conversation_history.append({"role": "user", "content": user_query})
        conversation_history.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    chatbot()
