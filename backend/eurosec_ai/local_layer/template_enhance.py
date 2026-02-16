from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import re


# ----------------------------
# Output DTO
# ----------------------------
@dataclass(frozen=True)
class EnhancementResult:
    text: str
    meta: Dict[str, object] | None = None


# ----------------------------
# Basic regex utilities
# ----------------------------
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

# lines that are usually NOT content
_JUNK_LINE_RE = re.compile(
    r"^\s*(\[REDACTED_[A-Z_]+\]|"
    r"(tanay|khilare)\b|"
    r"(stuttgart|germany)\b|"
    r"(linkedin|leetcode)\b.*|"
    r")\s*$",
    re.IGNORECASE,
)

# treat these as headings (CV + generic docs)
_HEADING_RE = re.compile(r"^\s*([A-Z][A-Z0-9 &/\-]{3,}|[A-Z][a-zA-Z ]{2,})\s*:?\s*$")

# bullet markers
_BULLET_RE = re.compile(r"^\s*(?:[-*•\u2022]|➢|›|»|o)\s+(.*)$")


def _norm_ws(s: str) -> str:
    return " ".join((s or "").replace("\u2022", " ").replace("•", " ").split()).strip()


def _is_heading(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    if len(s) > 70:
        return False
    if _BULLET_RE.match(s):
        return False
    return _HEADING_RE.match(s) is not None


def _looks_like_contact(line: str) -> bool:
    s = line or ""
    if _EMAIL_RE.search(s):
        return True
    if _PHONE_RE.search(s):
        return True
    if _URL_RE.search(s) and ("linkedin" in s.lower() or "leetcode" in s.lower()):
        return True
    return False


def _is_junk(line: str) -> bool:
    s = _norm_ws(line)
    if not s:
        return True
    if _looks_like_contact(s):
        return True
    if _JUNK_LINE_RE.match(s):
        return True
    # lines that are just punctuation or too short
    if len(s) < 4:
        return True
    # super common CV noise lines
    if s.lower() in {"curriculum vitae", "resume", "cv"}:
        return True
    return False


def _split_sections(text: str) -> Dict[str, List[str]]:
    """
    Split into simple sections by heading lines.
    Works for CVs + any doc.
    """
    raw = (text or "").strip()
    lines = [l.rstrip() for l in re.split(r"\r?\n+", raw) if l.strip()]
    if not lines:
        return {"Document": []}

    sections: Dict[str, List[str]] = {"Document": []}
    current = "Document"
    for line in lines:
        if _is_heading(line):
            current = line.strip().rstrip(":").title()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    # if headings were useless, just keep full doc as Document
    heading_cnt = sum(1 for k in sections.keys() if k != "Document")
    if heading_cnt < 2:
        return {"Document": lines}
    return sections


def _extract_items(lines: List[str]) -> Tuple[List[str], List[str]]:
    """
    Return: (bullets, sentences)
    """
    bullets: List[str] = []
    sentences: List[str] = []

    for line in lines:
        line = _norm_ws(line)
        if _is_junk(line):
            continue

        m = _BULLET_RE.match(line)
        if m:
            item = _norm_ws(m.group(1))
            if item and len(item) >= 10:
                bullets.append(item)
            continue

        # split long non-bullet lines into sentence-like chunks
        # keep deterministic and simple
        parts = re.split(r"(?<=[.!?])\s+| \|\s+|;\s+", line)
        for p in parts:
            p = _norm_ws(p)
            if len(p) >= 18 and not _looks_like_contact(p):
                sentences.append(p)

    return bullets, sentences


# ----------------------------
# Role tailoring logic
# ----------------------------
_ROLE_KEYWORDS: Dict[str, List[str]] = {
    "cybersecurity": [
        "security", "secure", "privacy", "gdpr", "encryption", "auth", "authentication",
        "authorization", "iam", "audit", "logging", "monitor", "incident", "vulnerability",
        "pentest", "network", "tcp", "ip", "firewall", "siem", "linux", "hardening",
        "docker", "kubernetes", "devops", "cloud", "aws", "azure", "it-security",
        "verification", "validation"
    ],
}


def _infer_target_role(user_text: str) -> Optional[str]:
    t = (user_text or "").lower()
    if "cyber" in t or "security" in t or "soc" in t:
        return "cybersecurity"
    return None


def _score_line_for_role(line: str, role: Optional[str]) -> int:
    if not role:
        return 0
    kws = _ROLE_KEYWORDS.get(role, [])
    low = (line or "").lower()
    return sum(1 for k in kws if k in low)


def _rewrite_bullet(line: str, role: Optional[str]) -> str:
    """
    Deterministic rewrite. Never invent facts.
    We only reframe the existing statement.
    """
    s = _norm_ws(line)
    if not s:
        return s

    # If already starts with a strong verb, keep it
    if re.match(r"^(built|developed|implemented|designed|integrated|automated|optimized|tested|secured|maintained)\b", s, re.IGNORECASE):
        return f"- {s[0].upper() + s[1:]}" if not s.startswith("- ") else s

    # Role-aware framing (safe)
    if role == "cybersecurity":
        templates = [
            "Applied secure engineering practices while {x}.",
            "Supported security and reliability requirements by {x}.",
            "Improved system robustness and operational safety by {x}.",
        ]
        # pick template deterministically based on length
        tpl = templates[len(s) % len(templates)]
        # lowercase first char for insertion
        x = s[0].lower() + s[1:] if s else s
        return f"- {tpl.format(x=x)}"

    # Generic rewrite
    return f"- Contributed to {s[0].lower() + s[1:]}"


def _extract_keywords_from_public_knowledge(public_knowledge: Optional[str]) -> List[str]:
    """
    Take the Internet Layer text and extract a clean keyword list.
    We avoid dumping a big guide into the CV rewrite.
    """
    if not public_knowledge:
        return []

    lines = [l.strip() for l in public_knowledge.splitlines() if l.strip()]
    out: List[str] = []
    for l in lines:
        l = re.sub(r"^[#>\-*•\u2022]+\s*", "", l).strip()
        if not l:
            continue
        # keep short items that look like skills/tools/responsibilities
        if len(l) <= 60 and not l.lower().startswith(("certainly", "here's", "responsibilities", "skills", "tools")):
            out.append(l)

    # dedupe
    seen = set()
    deduped: List[str] = []
    for x in out:
        nx = x.lower()
        if nx in seen:
            continue
        seen.add(nx)
        deduped.append(x)

    return deduped[:24]


def _format_keywords_block(keywords: List[str]) -> str:
    if not keywords:
        return ""
    return "## Role keywords (general, from Internet Layer)\n" + "\n".join(f"- {k}" for k in keywords) + "\n"


# ----------------------------
# Public API
# ----------------------------
def detect_doc_type(context_excerpt: str) -> str:
    low = (context_excerpt or "").lower()
    # very light heuristic
    if "education" in low and "skills" in low and ("experience" in low or "projects" in low):
        return "cv"
    return "document"


def enhance_with_context(
    intent: str,
    user_text: str,
    context_excerpt: str,
    public_knowledge: Optional[str] = None,
) -> EnhancementResult:
    """
    Offline template-based enhancement.
    Supports intents: rewrite / improve / tailor / bulletize / generic.
    """

    doc_type = detect_doc_type(context_excerpt)
    role = _infer_target_role(user_text)

    sections = _split_sections(context_excerpt)

    # extract items
    all_bullets: List[str] = []
    all_sents: List[str] = []

    for _, lines in sections.items():
        b, s = _extract_items(lines)
        all_bullets.extend(b)
        all_sents.extend(s)

    # Build a pool of candidate lines (bullets first, then sentences)
    pool = all_bullets + all_sents

    # For tailoring: SELECT relevant lines, don’t dump everything
    selected: List[str] = []
    if intent in {"tailor", "rewrite", "improve", "bulletize"}:
        if role:
            scored = [( _score_line_for_role(x, role), x) for x in pool]
            scored.sort(key=lambda t: (t[0], len(t[1])), reverse=True)
            # keep only lines with some relevance; fallback to top lines if nothing matches
            selected = [x for sc, x in scored if sc > 0][:18]
            if not selected:
                selected = [x for _, x in scored][:12]
        else:
            # generic rewrite: keep a reasonable amount, not all
            selected = pool[:14]
    else:
        selected = pool[:10]

    # Rewrite into professional bullets
    rewritten = [_rewrite_bullet(x, role) for x in selected]

    # Build output
    title = "Offline enhancement (template-based, local-only)\n"
    header = ""
    if doc_type == "cv":
        header += f"\nDetected document type: {doc_type}\n"
        if role:
            header += f"Target role: {role}\n"

    quick = f"\nQuick improvement summary:\n- rewrote {len(rewritten)} bullet(s)\n"

    keywords = _extract_keywords_from_public_knowledge(public_knowledge)
    kw_block = _format_keywords_block(keywords)

    # For CV tailoring, also keep an “Other skills from CV” block (optional)
    other_skills: List[str] = []
    if doc_type == "cv":
        # pick skill-like lines but do not flood output
        for x in all_bullets:
            if "," in x and len(x) <= 160:
                other_skills.append(_norm_ws(x))
        # dedupe and cap
        seen = set()
        ded = []
        for x in other_skills:
            nx = x.lower()
            if nx in seen:
                continue
            seen.add(nx)
            ded.append(x)
        other_skills = ded[:10]

    other_block = ""
    if other_skills:
        other_block = "## Other technical items found in the document\n" + "\n".join(f"- {s}" for s in other_skills) + "\n"

    final = (
        title
        + header
        + quick
        + "\n".join(rewritten)
        + "\n\n"
        + (other_block + "\n" if other_block else "")
        + (kw_block if kw_block else "")
    ).strip() + "\n"

    meta = {
        "doc_type": doc_type,
        "role": role or "",
        "bullets": len(rewritten),
        "paras": 0,  # kept for backward compatibility with your previous meta keys
        "keywords": len(keywords),
    }

    return EnhancementResult(text=final, meta=meta)
