"""Lightweight router for product-specific concerns.

This is separate from the clinical-pattern engine. It lets legitimate product
concerns such as skin appearance, vitamin support, weight management and liver
support reach the product database without pretending those concerns are
medical diagnoses.
"""
import re
from intent_parser import is_negated

PRODUCT_CONCERN_ALIASES = {
    "GloLux GlutaGlow Skin Effervescent Tablets": [
        "dull skin", "dry skin", "uneven skin tone", "uneven skin", "skin elasticity",
        "loss of skin elasticity", "early signs of aging", "early aging", "aging skin",
        "skin looks dull", "my skin looks dull", "skin is dull", "my skin has become dull", "dull complexion",
        "skin feels dry", "my skin feels dry", "my skin is dry", "skin dryness", "dehydrated skin", "my skin feels dehydrated",
        "uneven complexion", "patchy complexion", "uneven skin colour", "uneven skin color", "my skin tone is uneven",
        "skin has lost elasticity", "skin losing elasticity", "my skin is losing elasticity", "reduced skin elasticity",
        "skin lacks firmness", "loss of skin firmness", "fine lines", "wrinkles",
        "early signs of ageing", "early ageing", "ageing skin",
        "acne", "acne-prone skin", "acne prone skin", "acne breakouts",
        "cystic acne", "hormonal acne", "adult acne", "teenage acne", "acne flare-ups",
        "breakouts", "skin breakouts", "pimples", "pimple", "zits", "zit",
        "blackheads", "blackhead", "whiteheads", "whitehead",
        "acne blemishes", "skin blemishes", "blemishes", "acne spots",
        "acne marks", "post-acne marks", "acne scars", "post-acne scars",
        "glowing skin", "skin glow", "skin health", "dark skin", "hyperpigmentation",
        "patchy skin", "youthfulness", "fairness", "glutaglow", "glolux",
    ],
    "Apple Active": [
        "weight management", "weight management support", "manage my weight", "weight control",
        "slow metabolism", "metabolism support", "metabolism", "weight loss support",
        "weight management concerns",
        "want to lose weight", "wanting to lose weight", "i want to lose weight",
        "trying to lose weight", "trying to lose some weight", "need to lose weight",
        "help me lose weight", "help with losing weight", "looking to lose weight",
        "hoping to lose weight", "wish to lose weight", "goal is to lose weight",
        "unable to lose weight", "unalble to lose weight", "not able to lose weight",
        "can't lose weight", "cant lose weight", "cannot lose weight",
        "not losing weight", "i am not losing weight", "i'm not losing weight",
        "struggling to lose weight", "having trouble losing weight",
        "weight loss plateau", "stuck at my weight", "stubborn weight",
        "lose weight", "losing weight on purpose", "weight reduction",
        "reduce my weight", "reduce weight", "weight loss goal", "weight goals",
    ],
    "Guttify Poopie": [
        "low fibre intake", "low fiber intake", "low fibre", "low fiber",
        "irregular bowel movements", "constipation support",
    ],
    "Piles Pure": ["anal swelling", "swelling around anus", "swelling near anus", "swollen anus", "anal discomfort", "piles discomfort"],
    "Piloease Anal Care Spray": ["anal burning", "burning around anus", "burning near anus", "anal irritation", "anal itching", "anal discomfort"],
    "Liver Lift": [
        "liver support", "liver health", "digestion support",
    ],
}



# Business-provided bundles. Match explicit concern phrases only; clinical
# symptoms still go through GutGPT's safety/question/clinical-rule pipeline.
PRODUCT_BUNDLES = {
    "liver": ["Liver Lift", "Guttify Poopie"],
    # Weight-loss intent is a product concern, not a clinical diagnosis.
    # Keep this route limited to Apple Active, which is the catalog's weight
    # management product; unrelated gut/liver products must not be bundled in.
    "weight": ["Apple Active"],
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
        "weight": (
            "weight management", "weight control", "manage my weight", "weight loss support",
            "want to lose weight", "trying to lose weight", "unable to lose weight",
            "not losing weight", "weight loss goal", "weight reduction",
        ),
        "digestion": ("digestion support", "indigestion support"),
    }
    for bundle, terms in bundle_terms.items():
        matched_terms = [term for term in terms if _norm(term) in n and not is_negated(text, term)]
        if matched_terms:
            for product_name in PRODUCT_BUNDLES[bundle]:
                matches.append((product_name, matched_terms[0]))
    for product, aliases in PRODUCT_CONCERN_ALIASES.items():
        found = [a for a in aliases if _norm(a) in n and not is_negated(text, a)]
        if found:
            matches.append((product, max(found, key=len)))
    matches.sort(key=lambda x: len(x[1]), reverse=True)
    return matches
