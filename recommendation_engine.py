"""
Guttify Recommendation Engine — deterministic, database-only product matching.

No embedding model, no vector DB. The product decision is made entirely by
explicit rules over structured symptom data (see intent_parser.py) plus
light keyword matching. A product can only ever be returned if it was
actually loaded from products.json, and it can only score above zero if it
has an explicit primary-symptom match — general "digestion-adjacent"
similarity is never enough on its own.
"""
import json
import re

from gibberish_checker import is_gibberish, random_gibberish_response
from greeting_checker import is_greeting, random_greeting_response
from intent_parser import SymptomState, extract_named_aspect, merge_state
from safety_checker import check_safety

PRODUCTS_FILE = "products.json"
TOP_K = 2
MIN_SCORE = 100  # a product must have at least one primary-symptom hit
AMBIGUITY_MARGIN = 15  # if top two scores are this close, don't force a pick

PRIMARY_MATCH_POINTS = 100
SECONDARY_MATCH_POINTS = 10
FOOD_TRIGGER_MATCH_POINTS = 20
FOOD_RELATED_MATCH_POINTS = 10
CATEGORY_KEYWORD_POINTS = 2

with open(PRODUCTS_FILE, "r", encoding="utf-8") as file:
    products = json.load(file)


def normalize_text(text):
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _product_symptom_set(product):
    return {normalize_text(s) for s in product.get("symptoms", [])}


# ------------------------------------------------------------------
# Domain relevance — lightweight keyword vocab, no embeddings, used only
# to tell "off-topic" apart from "on-topic but under-described".
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
                vocab.add(word)
        for symptom in product.get("symptoms", []):
            for word in normalize_text(symptom).split():
                if len(word) >= 4:
                    vocab.add(word)
        for support in product.get("intended_support", []):
            for word in normalize_text(support).split():
                if len(word) >= 5:
                    vocab.add(word)
    return vocab


DOMAIN_VOCAB = _build_domain_vocab(products)


def has_domain_overlap(user_query):
    words = normalize_text(user_query).split()
    return any(len(w) >= 4 and w in DOMAIN_VOCAB for w in words)


# ------------------------------------------------------------------
# Named-product lookup — lets a user ask "what are the ingredients of X"
# directly, without describing a symptom at all.
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
            # Exclude tokens that double as ordinary symptom/category
            # vocabulary (e.g. "liver" from "Liver Lift" / "liver support")
            # so describing a symptom never gets mistaken for naming the
            # product outright.
            if t not in NAME_TOKEN_STOPWORDS and token_counts[t] == 1 and t not in DOMAIN_VOCAB
        ]
    return distinctive


DISTINCTIVE_NAME_TOKENS = _build_distinctive_name_tokens(products)


def find_named_product(user_query):
    """Return the product the user explicitly named, or None."""
    query_normalized = normalize_text(user_query)
    query_words = set(query_normalized.split())

    best_match, best_len = None, 0
    for product in products:
        if product.get("status") != "active":
            continue
        name_normalized = normalize_text(product.get("product_name", ""))
        if name_normalized and name_normalized in query_normalized and len(name_normalized) > best_len:
            best_match, best_len = product, len(name_normalized)
    if best_match:
        return best_match

    for product in products:
        if product.get("status") != "active":
            continue
        tokens = DISTINCTIVE_NAME_TOKENS.get(product["product_name"], [])
        if any(t in query_words for t in tokens):
            return product

    return None


def calculate_keyword_score(user_query, product):
    """Small supplementary score from raw text — never enough on its own
    to clear MIN_SCORE; only breaks ties/adds nuance on top of a real
    primary-symptom match."""
    query = normalize_text(user_query)
    score = 0
    category_words = normalize_text(product.get("category", "")).split()
    score += CATEGORY_KEYWORD_POINTS * sum(1 for w in category_words if len(w) >= 4 and w in query)
    return score


def score_product(product, state: SymptomState, raw_query: str):
    """
    Deterministic scoring. Critical rule: a product without a primary
    symptom match gets a score of zero, full stop — no partial credit
    from category/keyword overlap alone.
    """
    if state.red_flags:
        return 0

    symptom_set = _product_symptom_set(product)
    primary = normalize_text(state.primary_symptom) if state.primary_symptom else None

    if not primary or primary not in symptom_set:
        return 0

    score = PRIMARY_MATCH_POINTS

    for secondary in state.secondary_symptoms or []:
        if normalize_text(secondary) in symptom_set:
            score += SECONDARY_MATCH_POINTS

    if state.food_trigger:
        product_text = normalize_text(" ".join(
            product.get("symptoms", []) + product.get("intended_support", [])
            + [product.get("how_to_use", "")]
        ))
        if state.food_trigger.split("_")[0] in product_text:
            score += FOOD_TRIGGER_MATCH_POINTS
        elif state.food_related:
            score += FOOD_RELATED_MATCH_POINTS
    elif state.food_related:
        score += FOOD_RELATED_MATCH_POINTS

    score += calculate_keyword_score(raw_query, product)
    return score


def score_all_products(state: SymptomState, raw_query: str):
    candidates = []
    for product in products:
        if product.get("status") != "active":
            continue
        score = score_product(product, state, raw_query)
        if score > 0:
            candidates.append({"product": product, "score": score})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def _build_recommendation(product, score=None):
    return {
        "product_name": product["product_name"],
        "category": product["category"],
        "score": score,
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

NO_MATCH_MESSAGE = (
    "I couldn't find a closely matching Guttify product based on what "
    "you've shared. Could you tell me a bit more about what you're "
    "experiencing?"
)

AMBIGUOUS_MESSAGE = (
    "A couple of products could fit what you've described, and I don't "
    "want to guess. Could you share a little more detail about your main "
    "symptom?"
)


def evaluate(state: SymptomState, raw_query: str):
    """
    Deterministic evaluation over the current structured symptom state.
    Returns one of: RECOMMENDATION_FOUND, AMBIGUOUS, NO_MATCH.
    Never invents a product name; only products loaded from products.json
    can appear in the result.
    """
    if not state.primary_symptom:
        return {"status": "NO_MATCH", "recommendations": [], "message": NO_MATCH_MESSAGE}

    candidates = score_all_products(state, raw_query)
    if not candidates:
        return {"status": "NO_MATCH", "recommendations": [], "message": NO_MATCH_MESSAGE}

    top = candidates[0]
    if top["score"] < MIN_SCORE:
        return {"status": "NO_MATCH", "recommendations": [], "message": NO_MATCH_MESSAGE}

    if len(candidates) > 1:
        second = candidates[1]
        if (top["score"] - second["score"]) <= AMBIGUITY_MARGIN and second["score"] >= MIN_SCORE:
            return {
                "status": "AMBIGUOUS",
                "recommendations": [
                    _build_recommendation(top["product"], top["score"]),
                    _build_recommendation(second["product"], second["score"]),
                ],
                "message": AMBIGUOUS_MESSAGE,
            }

    top_candidates = candidates[:TOP_K]
    recommendations = [_build_recommendation(c["product"], c["score"]) for c in top_candidates]
    return {"status": "RECOMMENDATION_FOUND", "recommendations": recommendations, "message": ""}


def recommend_product(user_query, state: SymptomState = None):
    """
    Single-shot convenience wrapper (used by the CLI / simple callers that
    don't need multi-turn conversation management): runs gibberish + safety
    + named-product lookup + a one-shot structured extraction from the raw
    query, then evaluates deterministically.
    """
    if is_greeting(user_query):
        return {
            "status": "GREETING",
            "recommendations": [],
            "safety": None,
            "message": random_greeting_response(),
        }

    if is_gibberish(user_query):
        return {
            "status": "GIBBERISH",
            "recommendations": [],
            "safety": None,
            "message": random_gibberish_response(),
        }

    safety_result = check_safety(user_query)
    if not safety_result["safe_to_recommend"]:
        return {"status": "SAFETY_REVIEW", "recommendations": [], "safety": safety_result, "message": safety_result["message"]}

    named_product = find_named_product(user_query)
    if named_product:
        return {
            "status": "PRODUCT_INFO_FOUND",
            "recommendations": [_build_recommendation(named_product)],
            "safety": safety_result,
            "message": "",
        }

    state = merge_state(state or SymptomState(), user_query, safety_result.get("reasons") if safety_result.get("red_flag") else [])

    if not state.primary_symptom and not has_domain_overlap(user_query):
        return {
            "status": "IRRELEVANT",
            "recommendations": [],
            "safety": safety_result,
            "message": IRRELEVANT_MESSAGE,
        }

    result = evaluate(state, user_query)
    result["safety"] = safety_result
    return result


def display_product(recommendation, number):
    print(f"\n{number}. {recommendation['product_name']}")
    print(f"Category: {recommendation['category']}")
    if recommendation.get("score") is not None:
        print(f"Score: {recommendation['score']}")

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

    if status in ("GIBBERISH", "IRRELEVANT", "NO_MATCH", "AMBIGUOUS", "GREETING"):
        print("\n" + result["message"])

    elif status == "SAFETY_REVIEW":
        print("\n" + "=" * 60)
        print("             SAFETY REVIEW")
        print("=" * 60)
        print("\n" + result["safety"]["message"])
        print("\nReasons:")
        for reason in result["safety"]["reasons"]:
            print(f"- {reason}")

    elif status in ("RECOMMENDATION_FOUND", "PRODUCT_INFO_FOUND"):
        print("\n" + "=" * 60)
        print("          PRODUCT INFORMATION")
        print("=" * 60)
        for i, recommendation in enumerate(result["recommendations"], start=1):
            display_product(recommendation, i)
        print("\n" + "=" * 60)
