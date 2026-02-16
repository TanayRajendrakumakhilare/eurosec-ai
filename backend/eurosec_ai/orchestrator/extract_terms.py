from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import re

# Optional spaCy (graceful if model isn't available)
def _load_nlp():
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except Exception:
        return None

NLP = _load_nlp()

ROLE_REGEX = re.compile(
    r"\b(software engineer|devops|cloud engineer|data scientist|product manager|student|researcher|intern)\b",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class PublicTerms:
    roles: List[str]
    topics: List[str]

def extract_public_terms(text: str) -> PublicTerms:
    t = text or ""
    roles = list({m.group(1).lower() for m in ROLE_REGEX.finditer(t)})

    topics: List[str] = []
    if NLP is not None:
        doc = NLP(t)
        # Keep only non-sensitive-ish entities (very conservative)
        for ent in doc.ents:
            if ent.label_ in {"ORG", "PRODUCT", "EVENT", "WORK_OF_ART", "LANGUAGE"}:
                topics.append(ent.text)
        # Add noun chunks as "topics" candidates (short)
        for chunk in doc.noun_chunks:
            s = chunk.text.strip()
            if 2 <= len(s) <= 40:
                topics.append(s)
    else:
        # fallback: simple keyword-ish extraction
        candidates = re.findall(r"\b[a-zA-Z][a-zA-Z0-9\-\_]{2,}\b", t)
        topics.extend(candidates[:12])

    # de-dupe while preserving order
    seen = set()
    topics_dedup = []
    for x in topics:
        key = x.lower()
        if key not in seen:
            seen.add(key)
            topics_dedup.append(x)

    return PublicTerms(roles=roles[:5], topics=topics_dedup[:12])

def to_dict(pt: PublicTerms) -> Dict[str, object]:
    return {"roles": pt.roles, "topics": pt.topics}
