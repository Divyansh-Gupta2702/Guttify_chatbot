"""Guttify Product Assistant — one-shot RetrievalQA product recommendation CLI."""
import os

from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain_huggingface import ChatHuggingFace, HuggingFaceEmbeddings, HuggingFaceEndpoint

HF_TOKEN = os.environ.get("HF_TOKEN")
HUGGINGFACE_REPO_ID = "Qwen/Qwen2.5-3B-Instruct"
DB_FAISS_PATH = "vectorstore/db_faiss"

CUSTOM_PROMPT_TEMPLATE = """
You are Guttify's product recommendation assistant.

Your job is to recommend the most relevant Guttify product based ONLY
on the user's selected category and the retrieved product information.

IMPORTANT RULES:
1. You are NOT a doctor.
2. Never diagnose a disease or medical condition.
3. Never claim that a Guttify product cures or treats a disease.
4. Treat Guttify products as wellness/Ayurvedic/herbal supplements.
5. Never invent a Guttify product, ingredient, benefit, dosage, or side effect.
6. Use the retrieved context as the ONLY source of truth for product information.
7. Only recommend a product that is supported by the retrieved context.
8. Do not recommend unrelated products.
9. Always explicitly state the exact Guttify product name.

The user has selected this category:
{selected_category}

The user's original query is:
{question}

Use the retrieved product information below:
{context}

YOUR RESPONSE MUST FOLLOW THIS FORMAT:

Recommended Guttify Product:
[Exact product name]

Why this product:
[Explain why the product is relevant to the selected category and the
user's request. Use only information from the retrieved context.]

What it is intended to support:
[State the relevant purpose/benefits from the retrieved context.]

How to use:
[Give the usage instructions from the retrieved context.]

Important warnings:
[Give the relevant warnings and cautions from the retrieved context.]

Remember:
- Do not diagnose.
- Do not make medical claims.
- Do not invent information.
- Do not recommend products that are not supported by the retrieved context.
"""

# category -> (display name, expected product, product search boost query)
CATEGORIES = {
    "1": ("Digestion, bloating or constipation", "Digest Boost",
          "Digest Boost digestion bloating constipation irregular digestion"),
    "2": ("Acidity or heartburn", "Acid Ease",
          "Acid Ease acidity heartburn acid reflux gas"),
    "3": ("Liver support", "Liver Lift",
          "Liver Lift liver support detoxification fatigue metabolism digestion"),
    "4": ("Piles / hemorrhoid support", "Piles Pure",
          "Piles Pure piles hemorrhoids pain swelling bleeding straining"),
    "5": ("Weight management / metabolism", "Apple Active",
          "Apple Active weight management metabolism digestion bloating"),
}


def load_llm():
    llm = HuggingFaceEndpoint(
        repo_id=HUGGINGFACE_REPO_ID,
        provider="featherless-ai",
        temperature=0.5,
        max_new_tokens=512,
        huggingfacehub_api_token=HF_TOKEN,
    )
    return ChatHuggingFace(llm=llm)


def get_user_choice():
    print("\n" + "=" * 60)
    print("              GUTTIFY PRODUCT ASSISTANT")
    print("=" * 60)
    print("\nHi! How can I help you today?\n")
    print("Please select one of the following options:\n")
    for key, (category, _, _) in CATEGORIES.items():
        print(f"{key}. {category}")

    choice = input("\nEnter your choice (1-5): ").strip()
    while choice not in CATEGORIES:
        print("\nInvalid choice.")
        choice = input("Please enter a number between 1 and 5: ").strip()
    return choice


def main():
    prompt = PromptTemplate(
        template=CUSTOM_PROMPT_TEMPLATE,
        input_variables=["context", "question", "selected_category"],
    )
    embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    db = FAISS.load_local(DB_FAISS_PATH, embedding_model, allow_dangerous_deserialization=True)
    llm = load_llm()

    category, expected_product, search_query = CATEGORIES[get_user_choice()]
    print("\n" + "-" * 60)
    print(f"You selected: {category}")
    print("-" * 60)

    user_query = input("\nTell me a little more about what you are experiencing:\n> ").strip()

    combined_query = (
        f"Product category: {category}\n\n"
        f"Expected product: {expected_product}\n\n"
        f"Product search:\n{search_query}\n\n"
        f"User's concern:\n{user_query}"
    )

    retrieved_docs = db.similarity_search(combined_query, k=3)
    context = "\n\n".join(doc.page_content for doc in retrieved_docs)

    final_prompt = prompt.format(context=context, question=user_query, selected_category=category)
    response = llm.invoke(final_prompt)

    print("\n" + "=" * 60)
    print("                    RESULT")
    print("=" * 60 + "\n")
    print(response.content)


if __name__ == "__main__":
    main()
