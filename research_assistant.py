"""Small PubMed-first evidence retrieval for research-oriented questions.

Retrieval is read-only, bounded and fails closed. No customer identifiers or
assessment state are sent to PubMed or included in prompts.
"""
from __future__ import annotations
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from functools import lru_cache

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


@lru_cache(maxsize=64)
def search_pubmed(query: str, limit: int = 4, timeout: float = 5.0) -> list[dict]:
    clean = re.sub(r"[^\w\s:'()\-]", " ", str(query))[:300].strip()
    if not clean:
        return []
    params = urllib.parse.urlencode({"db": "pubmed", "term": clean, "retmode": "json", "retmax": max(1, min(4, int(limit))), "sort": "relevance"})
    request = urllib.request.Request(EUTILS + "esearch.fcgi?" + params, headers={"User-Agent": "GutGPT/1.0 (evidence lookup)"})
    with urllib.request.urlopen(request, timeout=max(2.0, min(8.0, timeout))) as response:
        ids = json.loads(response.read(50000).decode("utf-8")).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    summary_params = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    request = urllib.request.Request(EUTILS + "esummary.fcgi?" + summary_params, headers={"User-Agent": "GutGPT/1.0 (evidence lookup)"})
    with urllib.request.urlopen(request, timeout=max(2.0, min(8.0, timeout))) as response:
        data = json.loads(response.read(100000).decode("utf-8")).get("result", {})
    abstracts = {}
    fetch_params = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    fetch_request = urllib.request.Request(EUTILS + "efetch.fcgi?" + fetch_params, headers={"User-Agent": "GutGPT/1.0 (evidence lookup)"})
    try:
        with urllib.request.urlopen(fetch_request, timeout=max(2.0, min(8.0, timeout))) as response:
            root = ET.fromstring(response.read(180000))
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID")
            abstract = " ".join("".join(node.itertext()).strip() for node in article.findall(".//Abstract/AbstractText"))
            if pmid and abstract:
                abstracts[pmid] = abstract[:3500]
    except Exception:
        # Metadata remains useful, but the summarizer is told the abstract is absent.
        pass
    results = []
    for pmid in ids:
        row = data.get(pmid, {})
        if not row:
            continue
        results.append({"title": row.get("title", "Untitled"), "authors": [a.get("name", "") for a in row.get("authors", [])[:3]],
                        "pubdate": row.get("pubdate", "Date unavailable"), "journal": row.get("fulljournalname", ""),
                        "abstract": abstracts.get(pmid, "Abstract not retrieved"),
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "pmid": pmid})
    return results


def format_research_sources(records: list[dict]) -> str:
    return "\n".join(f"{i}. {r['title']} ({r['pubdate']}; {r['journal']}). Authors: {', '.join(r['authors']) or 'not listed'}. PMID: {r['pmid']}. Abstract: {r.get('abstract', 'Abstract not retrieved')}. {r['url']}" for i, r in enumerate(records, 1))
