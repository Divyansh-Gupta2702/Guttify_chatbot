"""Guttify Recommendation Engine — lightweight keyword + domain matching.

No embedding model here on purpose: sentence-transformers pulls in PyTorch,
which alone can eat 500MB-1GB of RAM before your app handles a single
request — too much for most free hosting tiers. This uses plain keyword
and vocabulary-overlap matching instead, which is enough for a catalog
this size and keeps the whole app's memory footprint tiny.
"""
import json
import re

from gibberish_checker import is_gibberish, random_gibberish_response
from safety_checker import check_safety

PRODUCTS_FILE = "products.json"
TOP_K = 3
MIN_KEYWORD_SCORE = 4

with open(PRODUCTS_FILE, "r", encoding="utf-8") as file:
    products = json.load(file)


def normalize_text(text):
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _stem(word):
    """Crude, dependency-free suffix stripping — not real stemming, just
    enough to match 'bloated'/'bloating'/'bloats' to the same root."""
    for suffix in ("ations", "ation", "ing", "ers", "er", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


# ------------------------------------------------------------------
# Domain relevance — used to tell "off-topic" apart from "needs detail"
# ------------------------------------------------------------------
GENERIC_DOMAIN_TERMS = {
    "gut", "digestion", "digestive", "stomach", "bowel", "supplement",
    "product", "ingredient", "ingredients", "tablet", "tablets", "spray",
    "capsule", "capsules", "health", "wellness", "symptom", "symptoms",
    "dosage", "usage", "warning", "warnings", "flavor", "flavour", "link",
}


def _build_domain_vocab(products):
    vocab = set(GENERIC_DOMAIN_TERMS)
    for product in products:
        for word in normalize_text(product.get("category", "")).split():
            if len(word) >= 4:
                vocab.add(_stem(word))
        for symptom in product.get("symptoms", []):
            for word in normalize_text(symptom).split():
                if len(word) >= 4:
                    vocab.add(_stem(word))
        for support in product.get("intended_support", []):
            for word in normalize_text(support).split():
                if len(word) >= 5:
                    vocab.add(_stem(word))
    return vocab


DOMAIN_VOCAB = _build_domain_vocab(products)


def has_domain_overlap(user_query):
    words = normalize_text(user_query).split()
    return any(len(w) >= 4 and _stem(w) in DOMAIN_VOCAB for w in words)


# ------------------------------------------------------------------
# Named-product lookup — lets a user ask "what are the ingredients of
# X" directly, without needing to describe a symptom at all.
# ------------------------------------------------------------------
NAME_TOKEN_STOPWORDS = {
    "guttify", "boost", "vitamin", "tablet", "tablets", "spray",
    "effervescent", "skin", "care", "anal",
}


def _build_distinctive_name_tokens(products):
    token_counts = {}
    product_tokens = {}
    for product in products:
        tokens = [
            t for t in normalize_text(product.get("product_name", "")).split()
            if len(t) >= 4 or any(c.isdigit() for c in t)
        ]
        product_tokens[product["product_name"]] = tokens
        for t in set(tokens):
            token_counts[t] = token_counts.get(t, 0) + 1

    distinctive = {}
    for product in products:
        name = product["product_name"]
        distinctive[name] = [
            t for t in product_tokens[name]
            if t not in NAME_TOKEN_STOPWORDS and token_counts[t] == 1
        ]
    return distinctive


DISTINCTIVE_NAME_TOKENS = _build_distinctive_name_tokens(products)


def find_named_product(user_query):
    """Return the product the user explicitly named, or None."""
    query_normalized = normalize_text(user_query)
    query_words = set(query_normalized.split())

    # 1. Exact full product-name match — the strongest possible signal.
    best_match, best_len = None, 0
    for product in products:
        if product.get("status") != "active":
            continue
        name_normalized = normalize_text(product.get("product_name", ""))
        if name_normalized and name_normalized in query_normalized and len(name_normalized) > best_len:
            best_match, best_len = product, len(name_normalized)
    if best_match:
        return best_match

    # 2. A single distinctive token unique to one product (e.g. "b12",
    # "poopie", "piloease") — covers shorthand mentions.
    for product in products:
        if product.get("status") != "active":
            continue
        tokens = DISTINCTIVE_NAME_TOKENS.get(product["product_name"], [])
        if any(t in query_words for t in tokens):
            return product

    return None


def calculate_keyword_score(user_query, product):
    query = normalize_text(user_query)
    query_words = {_stem(w) for w in query.split()}
    score = 0

    for symptom in product.get("symptoms", []):
        symptom_norm = normalize_text(symptom)
        if not symptom_norm:
            continue
        if symptom_norm in query:
            score += 10  # exact phrase match — strongest signal
            continue
        symptom_words = [_stem(w) for w in symptom_norm.split() if len(w) >= 4]
        if not symptom_words:
            continue
        overlap = sum(1 for w in symptom_words if w in query_words)
        if overlap == len(symptom_words):
            score += 8  # all significant words present, just reordered/reworded
        elif overlap:
            score += 3 * overlap  # partial credit for a related but incomplete match

    category_words = [_stem(w) for w in normalize_text(product.get("category", "")).split() if len(w) >= 4]
    score += 2 * sum(1 for w in category_words if w in query_words)

    for support in product.get("intended_support", []):
        support_words = [_stem(w) for w in normalize_text(support).split() if len(w) >= 5]
        score += sum(1 for w in support_words if w in query_words)

    return score


def score_all_products(user_query):
    """Score every active product against the query, best match first."""
    candidates = []

    for product in products:
        if product.get("status") != "active":
            continue

        keyword_score = calculate_keyword_score(user_query, product)
        candidates.append({"product": product, "keyword_score": keyword_score})

    candidates.sort(key=lambda c: c["keyword_score"], reverse=True)
    return candidates


def find_relevant_products(user_query, top_k=TOP_K):
    candidates = score_all_products(user_query)
    recommended = [c for c in candidates if c["keyword_score"] >= MIN_KEYWORD_SCORE]
    return recommended[:top_k]


def _build_recommendation(product, match=None):
    return {
        "product_name": product["product_name"],
        "category": product["category"],
        "keyword_score": match["keyword_score"] if match else None,
        "intended_support": product["intended_support"],
        "ingredients": product["ingredients"],
        "how_to_use": product["how_to_use"],
        "warnings": product["warnings"],
        "age_group": product.get("age_group", ""),
        "product_url": product.get("product_url", ""),
        "flavors": product.get("flavors", []),
        "variants": product.get("variants", []),
    }


IRRELEVANT_MESSAGE = (
    "The information you provided is not relevant to the products I can "
    "assist you with. Please ask me something related to our products."
)


def recommend_product(user_query):
    if is_gibberish(user_query):
        return {
            "status": "GIBBERISH",
            "recommendations": [],
            "safety": None,
            "message": random_gibberish_response(),
        }

    safety_result = check_safety(user_query)
    if not safety_result["safe_to_recommend"]:
        return {"status": "SAFETY_REVIEW", "recommendations": [], "safety": safety_result}

    # If the user names a specific product ("what's in Piloease?"), answer
    # about that exact product directly — no symptom description needed.
    named_product = find_named_product(user_query)
    if named_product:
        return {
            "status": "PRODUCT_INFO_FOUND",
            "recommendations": [_build_recommendation(named_product)],
            "safety": safety_result,
        }

    candidates = score_all_products(user_query)
    top = candidates[0] if candidates else None

    in_domain = bool(top) and (top["keyword_score"] > 0 or has_domain_overlap(user_query))

    if not in_domain:
        return {
            "status": "IRRELEVANT",
            "recommendations": [],
            "safety": safety_result,
            "message": IRRELEVANT_MESSAGE,
        }

    matches = [c for c in candidates if c["keyword_score"] >= MIN_KEYWORD_SCORE][:TOP_K]

    if not matches:
        return {"status": "NO_MATCH", "recommendations": [], "safety": safety_result}

    recommendations = [_build_recommendation(m["product"], m) for m in matches]
    return {"status": "RECOMMENDATION_FOUND", "recommendations": recommendations, "safety": safety_result}


def display_product(recommendation, number):
    print(f"\n{number}. {recommendation['product_name']}")
    print(f"Category: {recommendation['category']}")
    if recommendation.get("keyword_score") is not None:
        print(f"Keyword score: {recommendation['keyword_score']}")

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

    user_query = input("\nTell me what you're experiencing (or ask about a product):\n> ").strip()
    if not user_query:
        print("\nPlease describe what you're experiencing.")
        raise SystemExit

    result = recommend_product(user_query)
    status = result["status"]

    if status == "GIBBERISH":
        print("\n" + result["message"])

    elif status == "IRRELEVANT":
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

    elif status in ("RECOMMENDATION_FOUND", "PRODUCT_INFO_FOUND"):
        print("\n" + "=" * 60)
        print("          PRODUCT INFORMATION")
        print("=" * 60)
        for i, recommendation in enumerate(result["recommendations"], start=1):
            display_product(recommendation, i)
        print("\n" + "=" * 60)
