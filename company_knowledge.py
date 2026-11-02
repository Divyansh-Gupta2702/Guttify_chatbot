"""Curated, source-attributed Guttify company knowledge.

Only public facts reviewed from the official Guttify storefront are stored here.
Product attributes remain sourced from products.json at runtime.
"""
from __future__ import annotations

import json
from pathlib import Path

COMPANY_KNOWLEDGE = [
    {"topic": "company_identity", "fact": "Guttify says its mission is to make gut health simple, effective and enjoyable, with products designed for modern lifestyles.", "source": "https://guttify.co.in/pages/about-us"},
    {"topic": "company_history", "fact": "Guttify's About Us page describes the initial realization in 2023, science and formulation work in 2024, and the birth of Guttify in 2025.", "source": "https://guttify.co.in/pages/about-us"},
    {"topic": "science_framework", "fact": "Guttify describes its science loop as Test, Interpret, Intervene, Track and Learn, combining screening, biological signals, ingredient research, formulation science and consumer outcomes.", "source": "https://guttify.co.in/pages/the-science"},
    {"topic": "research_approach", "fact": "The Guttify science page says its research framework considers microbial signals, digestive symptoms, bowel patterns, dietary behaviour, lifestyle factors, ingredient response and longitudinal outcomes.", "source": "https://guttify.co.in/pages/the-science"},
    {"topic": "ingredient_quality", "fact": "Guttify describes research into ingredient characterization, including HPLC-based analysis of selected botanical ingredients and marker compounds, as part of its R&D framework. The page says methods and marker panels vary by ingredient and validation stage.", "source": "https://guttify.co.in/pages/the-science"},
    {"topic": "gut_scan", "fact": "The Gut Scan Kit page describes an at-home, saliva-based gut wellness kit with a colour-based result, a personalized gut-health report, dietary and lifestyle insights, and guidance for a daily routine. The page describes next-day results and storage at 2–8°C. It is presented as a wellness/educational tool, not a medical diagnosis.", "source": "https://guttify.co.in/products/gut-scan-kit-pack-of-2"},
    {"topic": "support_contact", "fact": "Guttify's Contact Us page lists support email guttify01@gmail.com and phone +91 9818693589. Customer service hours are Monday to Friday, 10:00 AM–7:00 PM; weekends are closed.", "source": "https://guttify.co.in/pages/contact-us"},
    {"topic": "business_address", "fact": "The Contact Us page lists IDEAWISE TECHNOLOGIES PVT LTD, Kh no. 115, Block N, H.No. 60, Vijay Vihar, Uttamnagar, New Delhi – 110059, India as the registered business address.", "source": "https://guttify.co.in/pages/contact-us"},
    {"topic": "wellness_categories", "fact": "The storefront organizes products by wellness goals including Digestion & Daily Regularity, Digestive Comfort, Liver Wellness, Bowel & Rectal Wellness and Metabolic Wellness.", "source": "https://guttify.co.in/"},
]


def retrieve_company_context(query: str, products=None, limit: int = 8) -> list[dict]:
    """Return relevant public company facts plus matching catalog records."""
    terms = {w for w in str(query).lower().split() if len(w) > 2}
    scored = []
    for item in COMPANY_KNOWLEDGE:
        text = (item["topic"] + " " + item["fact"]).lower()
        score = sum(1 for term in terms if term in text)
        if score:
            scored.append((score, item))
    facts = [item for _, item in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]
    product_hits = []
    for product in products or []:
        haystack = " ".join([str(product.get("product_name", "")), str(product.get("category", "")),
                             " ".join(product.get("symptoms", [])), " ".join(product.get("intended_support", []))]).lower()
        if any(term in haystack for term in terms):
            product_hits.append({k: product.get(k) for k in ("product_name", "category", "intended_support", "ingredients", "how_to_use", "warnings", "age_group", "product_url")})
    return facts + [{"topic": "approved_product_catalog", "fact": json.dumps(product_hits[:4], ensure_ascii=False), "source": "products.json (approved catalog)"}] if product_hits else facts
