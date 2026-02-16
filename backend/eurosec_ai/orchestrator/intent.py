# backend/eurosec_ai/orchestrator/intent.py
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class IntentResult:
    intent: str


_SMALLTALK_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|thanks|thank you|ok|okay|cool|nice|good|great|bye|goodbye)\s*[!.]*\s*$",
    re.IGNORECASE,
)

_SUMMARIZE_RE = re.compile(r"\b(summarize|summary|tl;dr|tldr)\b", re.IGNORECASE)
_REWRITE_RE = re.compile(r"\b(rewrite|rephrase|improve|polish|correct)\b", re.IGNORECASE)
_SEARCH_RE = re.compile(r"\b(find|search|locate|look for)\b", re.IGNORECASE)
_FILE_HINT_RE = re.compile(r'file\s*:\s*".+?"|file\s*:\s*\S+|file\s*"', re.IGNORECASE)


def classify_intent(user_text: str) -> IntentResult:
    t = (user_text or "").strip()

    # 1) small talk / greeting
    if _SMALLTALK_RE.match(t):
        return IntentResult(intent="smalltalk")

    # 2) summarize
    if _SUMMARIZE_RE.search(t):
        return IntentResult(intent="summarize")

    # 3) rewrite/enhance
    if _REWRITE_RE.search(t):
        return IntentResult(intent="rewrite")

    # 4) explicit file/search wording
    if _SEARCH_RE.search(t) or _FILE_HINT_RE.search(t):
        return IntentResult(intent="file_search")

    # default
    return IntentResult(intent="general_question")
