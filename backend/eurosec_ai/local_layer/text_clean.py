from __future__ import annotations

from dataclasses import dataclass
from typing import List

def _load_nlp():
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except Exception:
        return None

NLP = _load_nlp()


@dataclass(frozen=True)
class CleanedText:
    cleaned: str
    sentences: List[str]


def clean_text(text: str, max_sentences: int = 20, max_chars: int = 50_000) -> CleanedText:
    raw = (text or "").strip()
    if not raw:
        return CleanedText(cleaned="", sentences=[])

    raw = " ".join(raw.split())  # normalize whitespace
    raw = raw[:max_chars]

    if NLP is None:
        # fallback sentence split
        sents = [s.strip() for s in raw.split(".") if s.strip()]
        sents = [s + "." for s in sents[:max_sentences]]
        cleaned = "\n".join(sents)
        return CleanedText(cleaned=cleaned, sentences=sents)

    doc = NLP(raw)
    sents = [s.text.strip() for s in doc.sents if s.text.strip()]
    sents = sents[:max_sentences]
    cleaned = "\n".join(sents)
    return CleanedText(cleaned=cleaned, sentences=sents)
