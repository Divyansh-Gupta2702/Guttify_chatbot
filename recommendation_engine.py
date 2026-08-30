"""Guttify Recommendation Engine — hybrid semantic + keyword product matching."""
import json
import re

from langchain_huggingface import HuggingFaceEmbeddings

from gibberish_checker import is_gibberish, random_gibberish_response
from safety_checker import check_safety

PRODUCTS_FILE = "products.json"
TOP_K = 3
MIN_SEMANTIC_SCORE = 0.45
MIN_KEYWORD_SCORE = 2
NOT_RELEVANT_MESSAGE = "The information you provided is not relevant to Guttify products. Please ask about a Guttify product, its ingredients, usage, benefits, warnings, or a related concern."

with open(PRODUCTS_FILE, "r", encoding="utf-8") as file:
    products = json.load(file)

print("\nLoading embedding model...")
embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


def create_product_search_text(product):
    symptoms = ", ".join(product.get("symptoms", []))
    intended_support = ", ".join(product.get("intended_support", []))
    ingredients = ", ".join(product.get("ingredients", []))
    return (
        f"Product: {product.get('product_name', '')}\n"
        f"Category: {product.get('category', '')}\n"
        f"Symptoms this product is associated with: {symptoms}\n"
        f"Intended support: {intended_support}\n"
        f"Ingredients: {ingredients}"
    )


print("Creating product embeddings...")
product_texts = [create_product_search_text(p) for p in products]
product_embeddings = embedding_model.embed_documents(product_texts)


def normalize_text(text):
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def calculate_keyword_score(user_query, product):
    query = normalize_text(user_query)
    score = 0
    if normalize_text(product.get("product_name", "")) in query:
        score += 50
    for ingredient in product.get("ingredients", []):
        if normalize_text(ingredient) in query:
            score += 15

    for symptom in product.get("symptoms", []):
        if normalize_text(symptom) and normalize_text(symptom) in query:
            score += 10

    category_words = normalize_text(product.get("category", "")).split()
    score += 2 * sum(1 for w in category_words if len(w) >= 4 and w in query)

    for support in product.get("intended_support", []):
        support_words = normalize_text(support).split()
        score += sum(1 for w in support_words if len(w) >= 5 and w in query)

    return score


def cosine_similarity(vector_a, vector_b):
    dot_product = sum(a * b for a, b in zip(vector_a, vector_b))
    magnitude_a = sum(a * a for a in vector_a) ** 0.5
    magnitude_b = sum(b * b for b in vector_b) ** 0.5
    if magnitude_a == 0 or magnitude_b == 0:
        return 0
    return dot_product / (magnitude_a * magnitude_b)


def is_product_related(user_query):
    query = normalize_text(user_query)
    if any(normalize_text(p.get("product_name", "")) in query for p in products):
        return True
    terms = "guttify digestion constipation bloating acidity heartburn reflux liver piles hemorrhoid haemorrhoid fissure anal itching irritation burning bowel stool metabolism weight skin vitamin supplement tablet spray powder fiber fibre ingredient ingredients composition benefits usage dosage warning warnings".split()
    return any(term in query.split() for term in terms)


def find_relevant_products(user_query, top_k=TOP_K):
    if not is_product_related(user_query):
        return []
    query_embedding = embedding_model.embed_query(user_query)
    candidates = []

    for index, product in enumerate(products):
        if product.get("status") != "active":
            continue

        semantic_score = cosine_similarity(query_embedding, product_embeddings[index])
        keyword_score = calculate_keyword_score(user_query, product)

        candidates.append({
            "product": product,
            "semantic_score": semantic_score,
            "keyword_score": keyword_score,
            "combined_score": semantic_score * 100 + keyword_score,
        })

    candidates.sort(key=lambda c: c["combined_score"], reverse=True)

    recommended = [
        c for c in candidates
        if c["semantic_score"] >= MIN_SEMANTIC_SCORE or c["keyword_score"] >= MIN_KEYWORD_SCORE
    ]

    return recommended[:top_k]


def recommend_product(user_query):
    if is_gibberish(user_query):
        return {
            "status": "GIBBERISH",
            "recommendations": [],
            "safety": None,
            "message": random_gibberish_response(),
        }

    if not is_product_related(user_query):
        return {"status": "NOT_RELEVANT", "recommendations": [], "safety": None, "message": NOT_RELEVANT_MESSAGE}

    safety_result = check_safety(user_query)
    if not safety_result["safe_to_recommend"]:
        return {"status": "SAFETY_REVIEW", "recommendations": [], "safety": safety_result}

    matches = find_relevant_products(user_query)
    no_match = not matches or (
        matches[0]["keyword_score"] == 0 and matches[0]["semantic_score"] < MIN_SEMANTIC_SCORE
    )
    if no_match:
        return {"status": "NO_MATCH", "recommendations": [], "safety": safety_result}

    recommendations = [
        {
            "product_name": m["product"]["product_name"],
            "category": m["product"]["category"],
            "semantic_score": round(m["semantic_score"], 3),
            "keyword_score": m["keyword_score"],
            "combined_score": round(m["combined_score"], 2),
            "intended_support": m["product"]["intended_support"],
            "ingredients": m["product"]["ingredients"],
            "how_to_use": m["product"]["how_to_use"],
            "warnings": m["product"]["warnings"],
            "age_group": m["product"].get("age_group", ""),
            "product_url": m["product"].get("product_url", ""),
            "flavors": m["product"].get("flavors", []),
            "variants": m["product"].get("variants", []),
        }
        for m in matches
    ]

    return {"status": "RECOMMENDATION_FOUND", "recommendations": recommendations, "safety": safety_result}


def display_product(recommendation, number):
    print(f"\n{number}. {recommendation['product_name']}")
    print(f"Category: {recommendation['category']}")
    print(f"Semantic score: {recommendation['semantic_score']}")
    print(f"Keyword score: {recommendation['keyword_score']}")
    print(f"Combined score: {recommendation['combined_score']}")

    print("\nWhy it may be relevant:")
    for support in recommendation["intended_support"]:
        print(f"- {support}")

    print("\nIngredients:")
    for ingredient in recommendation["ingredients"]:
        print(f"- {ingredient}")

    print("\nHow to use:")
    print(recommendation["how_to_use"])

    print("\nImportant warnings:")
    for warning in recommendation["warnings"]:
        print(f"- {warning}")

    if recommendation.get("product_url"):
        print("\nProduct link:")
        print(recommendation["product_url"])

    if recommendation.get("flavors"):
        print("\nAvailable flavors:")
        print(", ".join(recommendation["flavors"]))

    if recommendation.get("variants"):
        print("\nFlavor options:")
        for variant in recommendation["variants"]:
            print(f"- {variant['flavor']}: {variant['url']}")

    if recommendation.get("age_group"):
        print("\nAge group:")
        print(recommendation["age_group"])


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("       GUTTIFY RECOMMENDATION ENGINE")
    print("=" * 60)

    user_query = input("\nTell me what you're experiencing:\n> ").strip()
    if not user_query:
        print("\nPlease describe what you're experiencing.")
        raise SystemExit

    result = recommend_product(user_query)
    status = result["status"]

    if status in ("GIBBERISH", "NOT_RELEVANT"):
        print("\n" + result["message"])

    elif status == "SAFETY_REVIEW":
        print("\n" + "=" * 60)
        print("             SAFETY REVIEW")
        print("=" * 60)
        print("\n" + result["safety"]["message"])
        print("\nReasons:")
        for reason in result["safety"]["reasons"]:
            print(f"- {reason}")

    elif status == "NO_MATCH":
        print("\n" + "=" * 60)
        print("              NO MATCH")
        print("=" * 60)
        print("\nI couldn't identify a relevant Guttify product from the available product information.")
        print("\nPlease provide more details about what you're experiencing.")

    elif status == "RECOMMENDATION_FOUND":
        print("\n" + "=" * 60)
        print("          RECOMMENDED PRODUCTS")
        print("=" * 60)
        for i, recommendation in enumerate(result["recommendations"], start=1):
            display_product(recommendation, i)
        print("\n" + "=" * 60)
