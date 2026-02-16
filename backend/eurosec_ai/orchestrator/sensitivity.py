from __future__ import annotations

from dataclasses import dataclass
from typing import List
import re

@dataclass(frozen=True)
class SensitivityResult:
    sensitive: bool
    reasons: List[str]

# Practical GDPR-ish detectors (heuristic, extend later)
EMAIL = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", re.IGNORECASE)
PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{3,4}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
CREDITCARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
APIKEY_HINT = re.compile(r"\b(sk-[A-Za-z0-9]{10,}|api[_-]?key|secret|token)\b", re.IGNORECASE)

SENSITIVE_KEYWORDS = [
    "passport", "visa", "aadhar", "ssn", "social security",
    "bank", "iban", "credit card", "salary slip",
    "contract", "offer letter", "medical", "diagnosis",
    "address", "private", "confidential",
]

def detect_sensitive(text: str) -> SensitivityResult:
    t = text or ""
    low = t.lower()
    reasons: List[str] = []

    if EMAIL.search(t):
        reasons.append("email_detected")
    if PHONE.search(t):
        reasons.append("phone_detected")
    if IBAN.search(t):
        reasons.append("iban_detected")
    if CREDITCARD.search(t):
        reasons.append("card_number_like_detected")
    if APIKEY_HINT.search(t):
        reasons.append("secret_or_key_hint_detected")

    if any(k in low for k in SENSITIVE_KEYWORDS):
        reasons.append("sensitive_keyword")

    return SensitivityResult(sensitive=len(reasons) > 0, reasons=reasons)
