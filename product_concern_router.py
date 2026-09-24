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
        "glowing skin", "skin glow", "skin health", "glutaglow", "glolux",
    ],
    "Boost Vitamin B12": [
        "b12 deficiency", "vitamin b12 deficiency", "low b12", "b12", "low energy",
        "poor focus", "brain fog", "fatigue", "tiredness", "plant based diet",
        "plant-based diet", "vegan diet", "vegetarian diet", "nutrient gap",
    ],
    "Boost Vitamin D3+": [
        "vitamin d deficiency", "vitamin d", "low vitamin d", "low immunity", "weak bones",
        "low mood", "low sun exposure", "not getting enough sunlight", "little sunlight",
    ],
    "Apple Active": [
        "weight management", "weight management support", "manage my weight", "weight control",
        "metabolism support", "slow metabolism", "metabolism", "weight loss support",
    ],
    "Guttify Poopie": ["low fibre intake", "low fiber intake", "low fibre", "low fiber"],
    "Liver Lift": [
        "liver support", "liver health", "sluggishness", "sluggish", "digestion concerns",
        "digestive concerns", "fatigue",
    ],
}


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", (text or "").lower())).strip()


def detect_product_concerns(text):
    """Return (product_name, matched_phrase) pairs, longest/most-specific first."""
    n = _norm(text)
    matches = []
    for product, aliases in PRODUCT_CONCERN_ALIASES.items():
        found = [a for a in aliases if _norm(a) in n]
        if found:
            matches.append((product, max(found, key=len)))
    matches.sort(key=lambda x: len(x[1]), reverse=True)
    return matches
