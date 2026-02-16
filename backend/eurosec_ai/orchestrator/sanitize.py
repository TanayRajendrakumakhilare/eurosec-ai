from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import re

EMAIL = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", re.IGNORECASE)
PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{3,4}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
CREDITCARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

@dataclass(frozen=True)
class Sanitized:
    sanitized_text: str
    cloud_query: Optional[str]

def redact(text: str) -> str:
    t = text or ""
    t = EMAIL.sub("[REDACTED_EMAIL]", t)
    t = PHONE.sub("[REDACTED_PHONE]", t)
    t = IBAN.sub("[REDACTED_IBAN]", t)
    t = CREDITCARD.sub("[REDACTED_CARD]", t)
    return t

def build_cloud_query(user_text: str, roles: list[str], topics: list[str], intent: str) -> Sanitized:
    redacted = redact(user_text)

    # Cloud query MUST be public/general. Do not include raw/redacted private text.
    role_hint = roles[0] if roles else "user"
    topic_hint = ", ".join(topics[:6]) if topics else "the topic"

    if intent == "email":
        q = f"Write a generic professional email template for a {role_hint} about {topic_hint}."
    elif intent == "rewrite":
        q = f"Give general rewriting guidelines and a generic improved example for a {role_hint} about {topic_hint}."
    elif intent == "summarize":
        q = f"Explain how to summarize documents and provide a generic summary example about {topic_hint}."
    else:
        q = f"Answer generally (no personal data) for a {role_hint} about {topic_hint}."

    return Sanitized(sanitized_text=redacted, cloud_query=q)
