"""Lightweight router for product-specific concerns.

This is separate from the clinical-pattern engine. It lets legitimate product
concerns such as skin appearance, vitamin support, weight management and liver
support reach the product database without pretending those concerns are
medical diagnoses.
"""
import re

PRODUCT_CONCERN_ALIASES = {
    "GloLux GlutaGlow Skin Effervescent Tablets": [
        "dull skin", "dry skin", "uneven skin tone", "uneven skin", "skin elasticity",
        "loss of skin elasticity", "early signs of aging", "early aging", "aging skin",
        "glowing skin", "skin glow", "skin health", "dark skin", "hyperpigmentation",
        "patchy skin", "youthfulness", "fairness", "glutaglow", "glolux",
    ],
    "Apple Active": [
        "weight management", "weight management support", "manage my weight", "weight control",
        "slow metabolism", "metabolism support", "metabolism", "weight loss support",
        "weight management concerns",
    ],
    "Guttify Poopie": [
        "low fibre intake", "low fiber intake", "low fibre", "low fiber",
        "irregular bowel movements", "constipation support",
    ],
    "Piles Pure": ["anal swelling", "swelling around anus", "swelling near anus", "swollen anus", "anal discomfort", "piles discomfort"],
    "Piloease Anal Care Spray": ["anal burning", "burning around anus", "burning near anus", "anal irritation", "anal itching", "anal discomfort"],
    "Liver Lift": [
        "liver support", "liver health", "sluggishness", "sluggish", "digestion concerns",
        "digestive concerns", "digestion support", "fatigue",
    ],
}



# Business-provided bundles. Match explicit concern phrases only; clinical
# symptoms still go through GutGPT's safety/question/clinical-rule pipeline.
PRODUCT_BUNDLES = {
    "liver": ["Liver Lift", "Guttify Poopie"],
    "weight": ["Apple Active", "Guttify Poopie", "Liver Lift"],
    "digestion": ["Digest Boost", "Liver Lift"],
}

def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", (text or "").lower())).strip()


def detect_product_concerns(text):
    """Return (product_name, matched_phrase) pairs, longest/most-specific first."""
    n = _norm(text)
    matches = []
    bundle_terms = {
        "liver": ("liver support", "liver health", "liver concerns"),
        "weight": ("weight management", "weight control", "manage my weight", "weight loss support"),
        "digestion": ("digestion support", "digestion concerns", "digestive concerns", "indigestion support"),
    }
    for bundle, terms in bundle_terms.items():
        if any(_norm(term) in n for term in terms):
            for product_name in PRODUCT_BUNDLES[bundle]:
                matches.append((product_name, next(term for term in terms if _norm(term) in n)))
    for product, aliases in PRODUCT_CONCERN_ALIASES.items():
        found = [a for a in aliases if _norm(a) in n]
        if found:
            matches.append((product, max(found, key=len)))
    matches.sort(key=lambda x: len(x[1]), reverse=True)
    return matches
